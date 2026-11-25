"""Baseline: hold QQQ while it is above its 200-day average, otherwise sit in T-bills.

The simplest strategy that could match the momentum strategy's risk-adjusted return. Signal from day t's
close trades at day t+1's close (no look-ahead); each switch pays fees + slippage; cash earns the 13w T-bill
rate. Compared with momentum over the same dates. Run: python -m analysis.qqq_trend
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.common import NO_RISK, REARMED, build_runs
from analysis.edge_test import newey_west_ols
from backtest import FEES, SLIPPAGE, align_rf, metrics
from data import BENCHMARK
from risk import trend_ok

COST = FEES + SLIPPAGE
TRADING_DAYS = 252


def positions(on: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(target, held) from a boolean signal known at each close.

    Timing (project rule 1): the signal from day t's close is an order for day t+1's close, so the position
    only earns returns from day t+2 on. `target[t]` is the order filled at close t (decided at close t-1) and
    `held[t]` is the position carried through day t's return (the previous order): the signal shifted by 2 bars.
    """
    target = on.astype(float).shift(1).fillna(1.0)
    held = target.shift(1).fillna(1.0)
    return target, held


def overlay_returns(
    bench: pd.Series, on: pd.Series, rf: pd.Series, cost: float = COST
) -> tuple[pd.Series, int]:
    """Daily returns of holding `bench` while the boolean signal `on` is True, else T-bills, plus switch count."""
    target, held = positions(on)
    trades = target.diff().abs().fillna(0.0)
    r = held * bench.pct_change() + (1 - held) * align_rf(rf, bench.index)
    r = r - trades * cost                        # one-way cost on the whole portfolio at each switch
    return r, int(trades.sum())


def trend_returns(
    bench: pd.Series, rf: pd.Series, window: int = 200, cost: float = COST
) -> tuple[pd.Series, int]:
    """Daily returns of the QQQ-above-SMA rule and the number of switches (see `overlay_returns`)."""
    return overlay_returns(bench, trend_ok(bench, window), rf, cost)


def main() -> None:
    runs = build_runs()
    cols = {NO_RISK: runs.returns[NO_RISK], REARMED: runs.returns[REARMED], BENCHMARK: runs.returns[BENCHMARK]}
    counts = {}
    for w in (100, 150, 200):
        r, n = trend_returns(runs.bench, runs.rf, w)
        cols[f"QQQ trend {w}d"] = r.loc[runs.start:]
        counts[f"QQQ trend {w}d"] = n
    rets = pd.DataFrame(cols)
    print(f"Sample {runs.start.date()}..{rets.index[-1].date()}, costs on, cash earns T-bill rate\n")
    table = rets.apply(lambda s: metrics(s, runs.rf))
    table.loc["2022 return"] = rets.loc["2022"].add(1).prod() - 1
    table.loc["End value of $100k"] = (1 + rets).prod() * 100_000
    print(table.round(3).to_string())
    print("\nSwitches over the whole history:", counts)

    exc = rets.sub(align_rf(runs.rf, rets.index), axis=0)
    print("\nRegression on QQQ (alpha/yr, Newey-West t, beta):")
    for c in rets.columns:
        if c == BENCHMARK:
            continue
        reg = newey_west_ols(exc[c].to_numpy(), exc[BENCHMARK].to_numpy())
        print(f"  {c:<30} {reg['alpha_daily'] * TRADING_DAYS:+.1%}  t={reg['alpha_t']:.2f}  beta {reg['beta']:.2f}")


if __name__ == "__main__":
    main()
