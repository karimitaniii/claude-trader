"""Shared setup for the analysis scripts: build the daily return series once.

Run scripts from the repo root as modules, e.g. `python -m analysis.edge_test`.
Everything uses the same costs (fees + slippage) and PIT universe as `backtest.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from backtest import FEES, INIT_CASH, SLIPPAGE, simulate
from data import BENCHMARK, load_prices, load_risk_free
from risk import RiskLimits, RiskRun, run_with_risk
from signals import target_weights
from universe import load_universe, symbol_groups

LIVE_RULES = RiskLimits()  # what live.py enforces: hard stop, manual reset
REARMED_RULES = replace(LIVE_RULES, kill_manual_reset=False)  # proxy for "human reviewed and reset"

NO_RISK = "Momentum, no risk layer"
HARD_STOP = "Momentum + risk (hard stop)"
REARMED = "Momentum + risk (re-armed)"


def completed_bars(obj):
    """Drop rows dated today or later: during market hours yfinance returns a partial bar (as live.py does)."""
    return obj.loc[obj.index.normalize() < pd.Timestamp.today().normalize()]


@dataclass
class Runs:
    close: pd.DataFrame            # PIT universe closes (ffilled)
    weights: pd.DataFrame          # raw strategy targets (NaN = no order)
    groups: pd.Series              # risk group per symbol
    bench: pd.Series               # QQQ close
    rf: pd.Series                  # daily risk-free rate
    returns: pd.DataFrame          # daily returns: three strategy variants + QQQ
    portfolios: dict               # name -> vectorbt Portfolio
    risk_runs: dict                # name -> RiskRun (events etc.)
    start: pd.Timestamp            # first trading day


def build_runs(top_n: int = 8, lookback: int = 252, skip: int = 21, universe: str = "pit") -> Runs:
    close, eligible = load_universe(universe)
    close = completed_bars(close)
    bench = completed_bars(load_prices([BENCHMARK])[BENCHMARK].ffill())
    rf = load_risk_free()
    groups = symbol_groups(close.columns)
    weights = target_weights(close, top_n=top_n, lookback=lookback, skip=skip, eligible=eligible)
    start = weights.first_valid_index()

    portfolios = {NO_RISK: simulate(close, weights)}
    risk_runs: dict[str, RiskRun] = {}
    for name, limits in ((HARD_STOP, LIVE_RULES), (REARMED, REARMED_RULES)):
        run = run_with_risk(close, weights, groups, bench, limits, FEES + SLIPPAGE, INIT_CASH)
        risk_runs[name] = run
        portfolios[name] = simulate(close, run.orders)

    rets = {name: pf.returns().loc[start:] for name, pf in portfolios.items()}
    rets[BENCHMARK] = bench.pct_change().loc[start:]
    return Runs(close, weights, groups, bench, rf, pd.DataFrame(rets), portfolios, risk_runs, start)
