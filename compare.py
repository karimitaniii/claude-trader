"""Roadmap step 6: compare live paper results with what the backtest expected.

Reads the JSONL logs of the momentum runner (live.py, logs/) and the QQQ-trend runner
(trend_live.py, logs/trend/) and re-runs the same strategy ("shadow" backtest) from each one's first live
trade day, starting at the same equity, then reports:
  - live vs shadow equity and the tracking gap,
  - fill slippage vs the day's close (the backtest assumes 5 bps + 5 bps fees),
  - failed orders and alerts,
  - with both strategies live: their live equity head to head since the later start.

    python compare.py                       # both strategies
    python compare.py --strategy trend      # momentum | trend | both

The trend shadow mirrors the live runner, not the research backtest: 98% target weight, orders only when the
on/off state changes (the position drifts in between), and no interest on cash.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import FEES, SLIPPAGE
from data import BENCHMARK, load_prices
from live import LIMITS, LOG_DIR, PARAMS, previous_month_end
from risk import run_with_risk, trend_ok
from signals import target_weights, targets_from_signal_day
from trend_live import LIMITS as TREND_LIMITS, LOG_DIR as TREND_LOG_DIR, TARGET_WEIGHT
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


def shadow_trend_equity(
    bench: pd.Series, start: pd.Timestamp, init_equity: float, window: int = TREND_LIMITS.trend_window,
    target_weight: float = TARGET_WEIGHT, cost_rate: float = FEES + SLIPPAGE,
) -> pd.Series:
    """Equity of the live trend rule from `start` (the first live trade day), beginning in cash.

    Timing as live: the signal from day t-1's close is an order filled at day t's close. The position is
    only traded when the on/off state changes, so its weight drifts with QQQ in between (as in the live
    runner). Costs are charged on traded notional; cash earns nothing.
    """
    on = trend_ok(bench, window).shift(1)        # state ordered at close t-1, filled at close t
    ret = bench.pct_change()
    days = bench.loc[start:].index
    value, weight, state = init_equity, 0.0, False
    out = {}
    for day in days:
        if day != start:                          # the first live fill happens at `start`'s close
            value *= 1 + weight * ret[day]
            weight = weight * (1 + ret[day]) / (1 + weight * ret[day])   # QQQ share of equity after the move
        want = bool(on[day]) if pd.notna(on[day]) else True
        if want != state:
            new_weight = target_weight if want else 0.0
            value *= 1 - abs(new_weight - weight) * cost_rate
            weight, state = new_weight, want
        out[day] = value
    return pd.Series(out)


def head_to_head(a: pd.Series, b: pd.Series, names: tuple[str, str]) -> pd.DataFrame:
    """Both equity curves rebased to 1.0 on their first common date, with total return and max drawdown."""
    both = pd.DataFrame({names[0]: a, names[1]: b}).dropna()
    if both.empty:
        return pd.DataFrame()
    rebased = both / both.iloc[0]
    summary = pd.DataFrame({
        "return": rebased.iloc[-1] - 1,
        "max drawdown": (rebased / rebased.cummax() - 1).min(),
    })
    summary.attrs["start"], summary.attrs["end"] = rebased.index[0], rebased.index[-1]
    return summary


def report_strategy(name: str, log_dir: Path, shadow_fn, submit_cmd: str) -> pd.Series | None:
    """Print the live-vs-shadow report for one strategy. Returns its live equity, or None if nothing traded."""
    events = read_events(log_dir)
    fills = [e for e in events if e["kind"] == "fill"]
    alerts = [e for e in events if e["kind"] == "alert"]
    failed = [e for e in events if e["kind"] == "order_final"]
    print(f"\n##### {name} #####")
    print(f"Log events: {len(events)} | fills: {len(fills)} | failed/cancelled orders: {len(failed)} | alerts: {len(alerts)}")
    for a in alerts[-5:]:
        print(f"  alert {a['ts']}: {a['message']}")
    if not fills:
        print(f"No fills yet: nothing to compare. Run `{submit_cmd}` first.")
        return None

    start = min(trade_date(e["client_order_id"]) for e in fills)
    equity = live_equity(events)
    init = equity[equity.index < start].iloc[-1] if (equity.index < start).any() else equity.iloc[0]
    shadow = shadow_fn(start, init)
    both = pd.DataFrame({"live": equity, "backtest": shadow}).dropna()
    both["gap %"] = (both["live"] / both["backtest"] - 1) * 100

    print(f"\n=== {name}: live paper vs backtest from {start.date()} (start equity {init:,.0f}) ===")
    print(both.tail(15).round(2).to_string())
    if len(both):
        last = both.iloc[-1]
        print(f"Return: live {last.live / init - 1:+.2%}, backtest {last.backtest / init - 1:+.2%}, "
              f"gap {last['gap %']:+.2f} pts")

    prices = load_prices(sorted({e["symbol"] for e in fills}))
    slip = fill_slippage(events, prices)
    print(f"\n=== {name}: fills vs close (backtest assumes {SLIPPAGE * 1e4:.0f} bps slippage + {FEES * 1e4:.0f} bps fees) ===")
    print(slip.round({"fill": 2, "close": 2, "slippage_bps": 2}).to_string(index=False))
    print(f"Mean slippage {slip['slippage_bps'].mean():.1f} bps, worst {slip['slippage_bps'].max():.1f} bps")
    return equity


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", choices=["momentum", "trend", "both"], default="both")
    args = ap.parse_args()

    live_eq: dict[str, pd.Series] = {}
    if args.strategy in ("momentum", "both"):
        eq = report_strategy("Momentum", LOG_DIR, shadow_equity, "python live.py --submit")
        if eq is not None:
            live_eq["momentum"] = eq
    if args.strategy in ("trend", "both"):
        def trend_shadow(start: pd.Timestamp, init: float) -> pd.Series:
            return shadow_trend_equity(load_prices([BENCHMARK])[BENCHMARK].ffill(), start, init)

        eq = report_strategy("QQQ trend", TREND_LOG_DIR, trend_shadow, "python trend_live.py --submit")
        if eq is not None:
            live_eq["trend"] = eq
    if len(live_eq) == 2:
        h2h = head_to_head(live_eq["momentum"], live_eq["trend"], ("momentum", "trend"))
        if len(h2h):
            print(f"\n=== Live head to head, {h2h.attrs['start'].date()} .. {h2h.attrs['end'].date()} "
                  f"(each account's own equity, rebased) ===")
            print(h2h.round(4).to_string())
            print("Weeks, not days, before this means anything: one month of paper results is noise.")


if __name__ == "__main__":
    main()
