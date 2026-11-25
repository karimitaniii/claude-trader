"""Tech-like Nasdaq-100 (the strategy's universe) vs the full Nasdaq-100, same rules and costs.

Same 12-1 momentum, top 8, monthly, PIT membership. The risk layer only knows semis/hardware groups, so
other sectors are uncapped here. Caveat (free data): delisted/acquired names have no yfinance prices and are
dropped, which hurts coverage more outside tech; the report prints coverage so you can judge.
Run: python -m analysis.universe_compare
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.common import NO_RISK, REARMED, build_runs, completed_bars
from analysis.edge_test import newey_west_ols
from backtest import align_rf, metrics, simulate
from data import BENCHMARK
from signals import equal_weights
from universe import load_membership, load_sector_map, load_universe, membership_matrix, tech_intervals

TRADING_DAYS = 252


def sector_exposure(runs, by: pd.Series) -> pd.Series:
    """Average share of equity per group (no-risk portfolio), cash included."""
    pf = runs.portfolios[NO_RISK]
    sh = pf.asset_value(group_by=False).div(pf.value(), axis=0).loc[runs.start:]
    out = sh.T.groupby(by.reindex(sh.columns).fillna("other")).sum().T.mean()
    out["cash"] = 1 - out.sum()
    return out.sort_values(ascending=False)


def main() -> None:
    results, runs_by = {}, {}
    for kind in ("pit", "all"):
        runs = build_runs(universe=kind)
        runs_by[kind] = runs
    start = max(r.start for r in runs_by.values())  # compare over the same dates
    rf = runs_by["pit"].rf
    cols = {}
    for kind, label in (("pit", "tech-like"), ("all", "full NDX")):
        r = runs_by[kind].returns.loc[start:]
        cols[f"{label}: no risk"] = r[NO_RISK]
        cols[f"{label}: risk re-armed"] = r[REARMED]
        close, elig = load_universe(kind)
        ew = simulate(completed_bars(close), equal_weights(completed_bars(close), eligible=elig)).returns().loc[start:]
        cols[f"{label}: equal-weight all members"] = ew
    cols[BENCHMARK] = runs_by["pit"].returns.loc[start:, BENCHMARK]
    rets = pd.DataFrame(cols)

    print(f"Common sample {start.date()}..{rets.index[-1].date()}, costs on, $100k start\n")
    table = rets.apply(lambda s: metrics(s, rf))
    table.loc["2022 return"] = rets.loc["2022"].add(1).prod() - 1
    table.loc["End value ($)"] = (1 + rets).prod() * 100_000
    print(table.round(3).to_string())

    exc = rets.sub(align_rf(rf, rets.index), axis=0)
    print("\nRegression on QQQ (alpha/yr, Newey-West t, beta):")
    for c in rets.columns[:-1]:
        reg = newey_west_ols(exc[c].to_numpy(), exc[BENCHMARK].to_numpy())
        print(f"  {c:<38} {reg['alpha_daily'] * TRADING_DAYS:+.1%}  t={reg['alpha_t']:.2f}  beta {reg['beta']:.2f}")

    for kind in ("pit", "all"):
        # Count ALL point-in-time members, including names yfinance has no prices for.
        close, _ = load_universe(kind)
        close = completed_bars(close)
        iv = tech_intervals(load_membership(), load_sector_map(), tech_only=(kind == "pit"))
        members = membership_matrix(iv, close.index)
        priced = close.reindex(columns=members.columns).notna()
        missing = 1 - (members & priced).sum().sum() / members.sum().sum()
        print(f"\n{kind}: {members.shape[1]} member symbols, {missing:.1%} of member-days have no price (untradable)")
    allruns = runs_by["all"]
    print("\nFull-NDX momentum: average exposure by group (no risk layer)")
    print(sector_exposure(allruns, allruns.groups).round(3).to_string())

    g = (1 + rets[[c for c in rets.columns if "no risk" in c or c == BENCHMARK]]).cumprod() * 100_000
    ax = g.plot(logy=True, figsize=(10, 5), title="Tech-like vs full Nasdaq-100 momentum (log, after costs)")
    ax.set_ylabel("$")
    plt.tight_layout()
    plt.savefig("report/7_universe_compare.png", dpi=150)
    print("\nSaved report/7_universe_compare.png")


if __name__ == "__main__":
    main()
