"""Daily paper-trading runner (Alpaca PAPER account only).

Run once per trading day while the market is open, before ~15:35 ET:

    python live.py              # dry run against the paper account: plan + log, submit nothing
    python live.py --submit     # submit market-on-close orders to the paper account
    python live.py --offline    # dry run with no broker at all ($100k simulated account)
    python live.py --reset-kill-switch   # after reviewing a kill event: re-arm at current equity

Each run:
  1. logs fills/final status of earlier orders,
  2. refreshes prices and drops today's (incomplete) bar, so decisions use the last close only,
  3. updates the drawdown kill switch with last close equity (once per day),
  4. if killed: liquidates and stays in cash until a manual reset,
  5. on the first run of a new month: targets from the previous month-end close (same as the
     backtest), passed through the risk layer, turned into whole-share market-on-close orders.

Everything goes to logs/YYYY-MM-DD.jsonl; alerts are also printed to stderr.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from broker import AlpacaPaperBroker, Broker, OrderRequest, PaperSimBroker
from data import BENCHMARK, load_prices
from risk import KillSwitch, RiskLimits, apply_limits, trend_ok
from signals import targets_from_signal_day
from universe import load_universe, symbol_groups, unpriced_members, unpriced_symbols

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state" / "live_state.json"
LOG_DIR = ROOT / "logs"
ET = ZoneInfo("America/New_York")

PARAMS = {"top_n": 8, "lookback": 252, "skip": 21}  # untuned defaults, same as backtest.py
LIMITS = RiskLimits()
ORDER_PREFIX = "tm"
MAX_DATA_AGE_DAYS = 5


# ---------- pure helpers (unit tested) ----------

def completed_bars(df: pd.DataFrame | pd.Series, today: pd.Timestamp):
    """Drop rows dated today or later: during market hours yfinance returns a partial bar."""
    return df.loc[df.index.normalize() < today.normalize()]


def previous_month_end(index: pd.DatetimeIndex, today: pd.Timestamp) -> pd.Timestamp | None:
    """Last trading day in `index` before the current calendar month (the backtest's signal day)."""
    before = index[index < pd.Timestamp(year=today.year, month=today.month, day=1)]
    return before[-1] if len(before) else None


def plan_orders(
    target_w: pd.Series, positions: dict[str, float], prices: pd.Series, equity: float, date_tag: str
) -> list[OrderRequest]:
    """Whole-share orders that move current positions to target weights. Sells first."""
    symbols = sorted(set(target_w[target_w > 0].index) | set(positions))
    orders = []
    for s in symbols:
        w = float(target_w.get(s, 0.0))
        px = float(prices.get(s, float("nan")))
        if w > 0 and not (px > 0):
            raise ValueError(f"no usable price for target {s}")
        target_qty = math.floor(w * equity / px) if w > 0 else 0
        delta = target_qty - positions.get(s, 0.0)
        if abs(delta) < 1e-9:
            continue
        side = "buy" if delta > 0 else "sell"
        qty = int(abs(delta)) if side == "buy" else int(math.ceil(abs(delta) - 1e-9))
        if qty > 0:
            orders.append(OrderRequest(s, qty, side, f"{ORDER_PREFIX}-{date_tag}-{s}-{side}"))
    return sorted(orders, key=lambda o: o.side != "sell")


def liquidation_orders(positions: dict[str, float], date_tag: str) -> list[OrderRequest]:
    return [
        OrderRequest(s, int(math.ceil(q)), "sell", f"{ORDER_PREFIX}-{date_tag}-{s}-kill")
        for s, q in sorted(positions.items()) if q > 0
    ]


# ---------- state and logging ----------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_rebalance_month": None, "last_kill_check": None, "kill": None, "logged_orders": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def log_event(kind: str, **data) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rec = {"ts": now.isoformat(timespec="seconds"), "kind": kind, **data}
    with open(LOG_DIR / f"{now.astimezone(ET).date()}.jsonl", "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    line = f"[{kind}] " + ", ".join(f"{k}={v}" for k, v in data.items() if k not in ("targets", "orders"))
    print(line, file=sys.stderr if kind in ("alert", "error") else sys.stdout)


def kill_switch_from_state(state: dict) -> KillSwitch:
    ks = KillSwitch(LIMITS)
    if state.get("kill"):
        ks.peak, ks.killed, ks.days_killed = state["kill"]["peak"], state["kill"]["killed"], state["kill"]["days_killed"]
    return ks


def kill_switch_to_state(ks: KillSwitch) -> dict:
    return {"peak": ks.peak, "killed": ks.killed, "days_killed": ks.days_killed}


# ---------- the run ----------

def log_order_updates(broker: Broker, state: dict, today: pd.Timestamp) -> None:
    final = {"filled", "canceled", "expired", "rejected", "done_for_day", "replaced"}
    since = (today - timedelta(days=7)).date().isoformat()
    for o in broker.orders_since(since):
        cid = o.get("client_order_id") or ""
        if cid.startswith(ORDER_PREFIX + "-") and o["status"] in final and cid not in state["logged_orders"]:
            log_event("fill" if o["status"] == "filled" else "order_final", **o)
            if o["status"] != "filled":
                log_event("alert", message=f"order {cid} ended {o['status']}", filled_qty=o["filled_qty"])
            state["logged_orders"].append(cid)
    state["logged_orders"] = state["logged_orders"][-1000:]


def missing_last_session(broker: Broker, today: pd.Timestamp, last_bar: pd.Timestamp) -> bool:
    """Alert if the newest price bar is older than the previous trading session (the signal would be out of date)."""
    expected = broker.previous_session(today.date())
    if expected is None or last_bar.date() >= expected:
        return False
    log_event("alert", message=f"last bar {last_bar.date()} but the previous session was {expected}; aborting")
    return True


def submit_all(broker: Broker, orders: list[OrderRequest], submit: bool) -> bool:
    if not orders:
        log_event("no_orders")
        return True
    if not submit:
        log_event("dry_run", n_orders=len(orders), orders=[asdict(o) for o in orders])
        return False
    ok, why = broker.can_submit_moc()
    if not ok:
        log_event("alert", message=f"not submitting: {why}")
        return False
    all_ok = True
    for o in orders:
        try:
            log_event("order_submitted", **broker.submit_market_on_close(o))
        except Exception as e:  # keep going; every failure is logged and alerted
            all_ok = False
            log_event("error", where="submit", order=asdict(o), error=repr(e))
            log_event("alert", message=f"order failed: {o.client_order_id}")
    return all_ok


def run(broker: Broker, submit: bool, now: datetime | None = None) -> None:
    now = now or datetime.now(ET)
    today = pd.Timestamp(now.date())
    tag = today.strftime("%Y%m%d")
    state = load_state()
    log_event("run_start", mode="submit" if submit else "dry_run", broker=type(broker).__name__, params=PARAMS,
              limits=asdict(LIMITS))
    try:
        log_order_updates(broker, state, today)

        stocks, eligible = load_universe("pit", refresh=True)
        stocks, eligible = completed_bars(stocks, today), completed_bars(eligible, today)
        bench = completed_bars(load_prices([BENCHMARK], refresh=True)[BENCHMARK].ffill(), today)
        last_bar = stocks.index[-1]
        if (today - last_bar).days > MAX_DATA_AGE_DAYS:
            log_event("alert", message=f"stale data: last bar {last_bar.date()}; aborting")
            return
        trend = trend_ok(bench, LIMITS.trend_window)
        equity = broker.last_close_equity()
        positions = broker.positions()
        log_event("account", last_close_equity=equity, positions=positions, last_bar=last_bar.date(),
                  benchmark_above_trend=bool(trend.iloc[-1]))

        ks = kill_switch_from_state(state)
        if state.get("last_kill_check") != today.date().isoformat():
            event = ks.update(equity, bool(trend.iloc[-1]))
            state["kill"], state["last_kill_check"] = kill_switch_to_state(ks), today.date().isoformat()
            if event == "kill":
                log_event("alert", message=f"KILL SWITCH: equity {equity:,.0f} is {LIMITS.kill_drawdown:.0%} below "
                          f"peak {ks.peak:,.0f}. Liquidating; manual review + --reset-kill-switch required.")
        if ks.killed:
            if positions:
                submit_all(broker, liquidation_orders(positions, tag), submit)
            else:
                log_event("killed", message="kill switch active, holding cash until manual reset")
            return

        month = today.strftime("%Y-%m")
        if state.get("last_rebalance_month") == month:
            log_event("no_rebalance", message=f"already rebalanced for {month}")
            return
        if missing_last_session(broker, today, last_bar):
            return
        signal_day = previous_month_end(stocks.index, today)
        if signal_day is None:
            log_event("alert", message="no price data before this month; aborting")
            return
        unpriced = unpriced_members([signal_day, last_bar])
        if unpriced:
            log_event("alert", message=f"no price for {unpriced} on {signal_day.date()} or {last_bar.date()}; "
                      "aborting, re-run to download again")
            return
        raw = targets_from_signal_day(stocks, signal_day, eligible=eligible, **PARAMS)
        if raw is None:
            log_event("alert", message=f"no valid signal on {signal_day.date()}")
            return
        allowed, fired = apply_limits(raw, symbol_groups(stocks.columns), LIMITS, bool(trend.loc[signal_day]))
        log_event("signal", signal_day=signal_day.date(), targets={s: round(w, 4) for s, w in raw[raw > 0].items()})
        log_event("risk", fired=fired, gross=round(float(allowed.sum()), 4),
                  targets={s: round(w, 4) for s, w in allowed[allowed > 0].items()})
        stale = unpriced_symbols(list(allowed[allowed > 0].index), last_bar)
        if stale:
            log_event("alert", message=f"no price for target {stale} on {last_bar.date()}; aborting")
            return
        orders = plan_orders(allowed, positions, stocks.loc[last_bar], equity, tag)
        if submit_all(broker, orders, submit) and submit:
            state["last_rebalance_month"] = month
    except Exception as e:
        log_event("error", where="run", error=repr(e))
        log_event("alert", message=f"run failed: {e!r}")
        raise
    finally:
        save_state(state)
        log_event("run_end")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submit", action="store_true", help="submit orders to the Alpaca PAPER account")
    ap.add_argument("--offline", action="store_true", help="no broker: simulated $100k empty account")
    ap.add_argument("--reset-kill-switch", action="store_true", help="manual re-arm after reviewing a kill event")
    args = ap.parse_args()
    if args.offline and args.submit:
        ap.error("--offline cannot submit")
    if args.offline:  # never let simulated equity touch the real kill-switch state or logs
        global STATE_FILE, LOG_DIR
        STATE_FILE, LOG_DIR = ROOT / "state" / "offline_state.json", ROOT / "logs" / "offline"
    broker: Broker = PaperSimBroker() if args.offline else AlpacaPaperBroker()

    if args.reset_kill_switch:
        state = load_state()
        ks = kill_switch_from_state(state)
        ks.reset(broker.last_close_equity())
        state["kill"] = kill_switch_to_state(ks)
        save_state(state)
        log_event("manual_reset", new_peak=ks.peak)
        return
    run(broker, submit=args.submit)


if __name__ == "__main__":
    main()
