"""Roadmap step 6: compare live paper results with what the backtest expected.

Reads live.py's JSONL logs and re-runs the same strategy + risk layer ("shadow" backtest)
from the first live trade day, starting at the same equity, then reports:
  - live vs shadow equity and the tracking gap,
  - fill slippage vs the day's close (the backtest assumes 5 bps + 5 bps fees),
  - failed orders and alerts.

    python compare.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import FEES, SLIPPAGE
from data import BENCHMARK, load_prices
from live import LIMITS, LOG_DIR, PARAMS, previous_month_end
from risk import run_with_risk
from signals import target_weights, targets_from_signal_day
from universe import load_universe, symbol_groups


def read_events(log_dir: Path) -> list[dict]:
    return [json.loads(line) for f in sorted(log_dir.glob("*.jsonl")) for line in f.read_text().splitlines() if line]


def live_equity(events: list[dict]) -> pd.Series:
    """Account equity at each close, from `account` events (last_close_equity is as of `last_bar`)."""
    rows = {pd.Timestamp(e["last_bar"]): e["last_close_equity"] for e in events if e["kind"] == "account"}
    return pd.Series(rows, dtype=float).sort_index()


def trade_date(client_order_id: str) -> pd.Timestamp:
    """Order ids look like tm-YYYYMMDD-SYMBOL-side."""
    return pd.Timestamp(client_order_id.split("-")[1])


def fill_slippage(events: list[dict], close: pd.DataFrame) -> pd.DataFrame:
    """Per fill: signed cost vs that day's close in bps (positive = worse than the close)."""
    rows = []
    for e in events:
        if e["kind"] != "fill" or not e.get("filled_avg_price"):
            continue
        day, sym = trade_date(e["client_order_id"]), e["symbol"]
        ref = close[sym].get(day, np.nan) if sym in close else np.nan
        sign = 1 if e["side"] == "buy" else -1
        rows.append({"date": day, "symbol": sym, "side": e["side"], "qty": e["filled_qty"],
                     "fill": e["filled_avg_price"], "close": ref,
                     "slippage_bps": sign * (e["filled_avg_price"] / ref - 1) * 1e4})
    return pd.DataFrame(rows, columns=["date", "symbol", "side", "qty", "fill", "close", "slippage_bps"])


def shadow_equity(start: pd.Timestamp, init_equity: float) -> pd.Series:
    """Backtest the live configuration from `start`, beginning with `init_equity` in cash."""
    stocks, eligible = load_universe("pit")
    bench = load_prices([BENCHMARK])[BENCHMARK].ffill()
    weights = target_weights(stocks, eligible=eligible, **PARAMS)
    weights.loc[:start] = np.nan  # nothing before live trading began
    # shortcut: the first live trade may be mid-month on the previous month-end signal; mirror that.
    first = targets_from_signal_day(stocks, previous_month_end(stocks.index, start), eligible=eligible, **PARAMS)
    weights.loc[start] = first
    run = run_with_risk(stocks, weights, symbol_groups(stocks.columns), bench, LIMITS, FEES + SLIPPAGE, init_equity)
    return run.equity.loc[start:]


def main() -> None:
    events = read_events(LOG_DIR)
    fills = [e for e in events if e["kind"] == "fill"]
    alerts = [e for e in events if e["kind"] == "alert"]
    failed = [e for e in events if e["kind"] == "order_final"]
    print(f"Log events: {len(events)} | fills: {len(fills)} | failed/cancelled orders: {len(failed)} | alerts: {len(alerts)}")
    for a in alerts[-5:]:
        print(f"  alert {a['ts']}: {a['message']}")
    if not fills:
        print("No fills yet: nothing to compare. Run `python live.py --submit` on a rebalance day first.")
        return

    start = min(trade_date(e["client_order_id"]) for e in fills)
    equity = live_equity(events)
    init = equity[equity.index < start].iloc[-1] if (equity.index < start).any() else equity.iloc[0]
    shadow = shadow_equity(start, init)
    both = pd.DataFrame({"live": equity, "backtest": shadow}).dropna()
    both["gap %"] = (both["live"] / both["backtest"] - 1) * 100

    print(f"\n=== Live paper vs backtest from {start.date()} (start equity {init:,.0f}) ===")
    print(both.tail(15).round(2).to_string())
    if len(both):
        last = both.iloc[-1]
        print(f"Return: live {last.live / init - 1:+.2%}, backtest {last.backtest / init - 1:+.2%}, "
              f"gap {last['gap %']:+.2f} pts")

    prices = load_prices(sorted({e["symbol"] for e in fills}))
    slip = fill_slippage(events, prices)
    print(f"\n=== Fills vs close (backtest assumes {SLIPPAGE * 1e4:.0f} bps slippage + {FEES * 1e4:.0f} bps fees) ===")
    print(slip.round(2).to_string(index=False))
    print(f"Mean slippage {slip['slippage_bps'].mean():.1f} bps, worst {slip['slippage_bps'].max():.1f} bps")


if __name__ == "__main__":
    main()
