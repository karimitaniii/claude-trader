"""Daily paper-trading runner for the QQQ trend baseline (a SECOND Alpaca PAPER account).

Rule: hold 100% QQQ while QQQ's last completed close is at or above its 200-day average, otherwise cash.
Same timing as the backtest (`analysis/qqq_trend.py`): the signal from day t's close trades at day t+1's
close, via a market-on-close order. It runs next to `live.py` (momentum) so the two can be compared on live
data. The account holds positions and equity, so the strategies cannot share one paper account:

    export ALPACA_TREND_API_KEY=... ALPACA_TREND_SECRET_KEY=...   # keys of the second paper account
    python trend_live.py              # dry run: plan + log, submit nothing
    python trend_live.py --submit     # submit the market-on-close order to the trend paper account
    python trend_live.py --offline    # dry run with no broker ($100k simulated account)
    python trend_live.py --reset-kill-switch

Differences from the backtest: paper cash earns no T-bill interest, whole shares leave a little cash, and
the target is 98% of equity, not 100%: the order is sized on yesterday's close but fills at today's close, so a
fully invested order could exceed cash on a gap up and be rejected (the strategy would then never enter).
Same drawdown kill switch as live.py (hard stop, manual reset), so rule 4 holds here too. Logs go to
logs/trend/, state to state/trend_state.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

import live
from broker import AlpacaPaperBroker, Broker, OrderRequest, PaperSimBroker
from data import BENCHMARK, load_prices
from risk import KillSwitch, RiskLimits, trend_ok

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state" / "trend_state.json"
LOG_DIR = ROOT / "logs" / "trend"
KEY_ENV, SECRET_ENV = "ALPACA_TREND_API_KEY", "ALPACA_TREND_SECRET_KEY"

TARGET_WEIGHT = 0.98  # cash buffer for the close-to-close price move between sizing and fill

# Kill switch only: the trend rule itself is the sell-off rule, and there is one name at 100%.
LIMITS = RiskLimits(max_position=1.0, group_caps=(), selloff_gross=1.0)


def want_invested(bench: pd.Series, window: int = LIMITS.trend_window) -> bool:
    """True if QQQ's last close is at or above its trailing average (no restriction before `window` bars)."""
    return bool(trend_ok(bench, window).iloc[-1])


def plan_trend_orders(
    want_on: bool, positions: dict[str, float], price: float, equity: float, date_tag: str
) -> list[OrderRequest]:
    """Orders only when the on/off state changes, so share-count drift never causes daily churn."""
    held = positions.get(BENCHMARK, 0.0) > 0
    if want_on == held:
        return []
    target = pd.Series({BENCHMARK: TARGET_WEIGHT if want_on else 0.0})
    return live.plan_orders(target, positions, pd.Series({BENCHMARK: price}), equity, date_tag)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_kill_check": None, "last_submit_day": None, "kill": None, "logged_orders": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    os.replace(tmp, STATE_FILE)  # atomic: an interrupted save leaves the previous state, never half a file


def kill_switch_from_state(state: dict) -> KillSwitch:
    ks = KillSwitch(LIMITS)
    if state.get("kill"):
        ks.peak, ks.killed, ks.days_killed = state["kill"]["peak"], state["kill"]["killed"], state["kill"]["days_killed"]
    return ks


def kill_switch_to_state(ks: KillSwitch) -> dict:
    return {"peak": ks.peak, "killed": ks.killed, "days_killed": ks.days_killed}


def run(broker: Broker, submit: bool, now: datetime | None = None) -> None:
    live.LOG_DIR = LOG_DIR  # live.log_event writes here, so trend logs never mix with momentum logs
    now = now or datetime.now(live.ET)
    today = pd.Timestamp(now.date())
    tag = today.strftime("%Y%m%d")
    state = load_state()
    log_event = live.log_event
    log_event("run_start", strategy="qqq_trend", mode="submit" if submit else "dry_run",
              broker=type(broker).__name__, limits=asdict(LIMITS))
    try:
        equity, positions = broker.last_close_equity(), broker.positions()
        stray = sorted(s for s in positions if s != BENCHMARK)
        if stray:
            log_event("alert", message=f"unexpected positions in the trend account: {stray}; is it the wrong account?")
            return

        # The kill switch needs only the broker, so it runs before anything that can fail on market or order data.
        ks = kill_switch_from_state(state)
        if state.get("last_kill_check") != today.date().isoformat():
            ks.update(equity, False)  # the trend flag only matters for automatic re-arm, which is off
            state["kill"], state["last_kill_check"] = kill_switch_to_state(ks), today.date().isoformat()
            try:
                save_state(state)  # now: a killed process skips `finally`, and the later downloads can hang
            except OSError as e:
                if not ks.killed:  # trading on unsaved state could repeat orders on the next run
                    raise
                log_event("alert", message=f"could not save the kill state: {e!r}; liquidating anyway")
        if ks.killed:
            log_event("alert", message=f"KILL SWITCH active: equity {equity:,.0f}, peak {ks.peak:,.0f}, limit "
                      f"{LIMITS.kill_drawdown:.0%}. Manual review + --reset-kill-switch required.")
            if positions:
                live.submit_all(broker, live.liquidation_orders(positions, tag), submit)

        live.log_order_updates(broker, state, today)

        bench = live.completed_bars(load_prices([BENCHMARK], refresh=True)[BENCHMARK].ffill(), today)
        if len(bench) < LIMITS.trend_window:
            log_event("alert", message=f"unusable {BENCHMARK} history: {len(bench)} rows, need "
                      f"{LIMITS.trend_window}; aborting")
            return
        last_bar = bench.index[-1]
        if (today - last_bar).days > live.MAX_DATA_AGE_DAYS:
            log_event("alert", message=f"stale data: last bar {last_bar.date()}; aborting")
            return
        want_on = want_invested(bench)
        log_event("account", last_close_equity=equity, positions=positions, last_bar=last_bar.date(),
                  benchmark_above_trend=want_on)

        if ks.killed:
            if not positions:
                log_event("killed", message="kill switch active, holding cash until manual reset")
            return

        if state.get("last_submit_day") == today.date().isoformat():
            log_event("no_orders", message="already submitted today; the order fills at the close")
            return
        if live.missing_last_session(broker, today, last_bar):
            return
        orders = plan_trend_orders(want_on, positions, float(bench.iloc[-1]), equity, tag)
        log_event("signal", signal_day=last_bar.date(), invested=want_on, held=positions.get(BENCHMARK, 0.0) > 0)
        if submit and orders:  # fail before trading: unrecorded orders would be planned again
            save_state(state)
            log_event("pre_submit", required=True, n_orders=len(orders))
        if live.submit_all(broker, orders, submit) and submit and orders:
            state["last_submit_day"] = today.date().isoformat()
    except Exception as e:
        log_event("error", where="run", error=repr(e))
        log_event("alert", message=f"run failed: {e!r}")
        raise
    finally:
        save_state(state)
        log_event("run_end")


def main() -> None:
    global STATE_FILE, LOG_DIR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submit", action="store_true", help="submit orders to the trend PAPER account")
    ap.add_argument("--offline", action="store_true", help="no broker: simulated $100k empty account")
    ap.add_argument("--reset-kill-switch", action="store_true", help="manual re-arm after reviewing a kill event")
    args = ap.parse_args()
    if args.offline and args.submit:
        ap.error("--offline cannot submit")
    if args.offline:  # never let simulated equity touch the real kill-switch state or logs
        STATE_FILE, LOG_DIR = ROOT / "state" / "offline_trend_state.json", ROOT / "logs" / "offline_trend"
    elif os.environ.get(KEY_ENV) and os.environ.get(KEY_ENV) == os.environ.get("ALPACA_API_KEY"):
        ap.error(f"{KEY_ENV} equals ALPACA_API_KEY: the trend strategy needs its own paper account")
    broker: Broker = PaperSimBroker() if args.offline else AlpacaPaperBroker(KEY_ENV, SECRET_ENV)

    if args.reset_kill_switch:
        live.LOG_DIR = LOG_DIR
        state = load_state()
        ks = kill_switch_from_state(state)
        ks.reset(broker.last_close_equity())
        state["kill"] = kill_switch_to_state(ks)
        save_state(state)
        live.log_event("manual_reset", new_peak=ks.peak)
        return
    run(broker, submit=args.submit)


if __name__ == "__main__":
    main()
