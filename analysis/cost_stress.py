"""Cost stress test: how much does each strategy depend on the 5 bps slippage assumption?

Re-runs the PIT momentum strategy (no risk layer, and the re-armed risk layer) and the QQQ 200d trend rule at
5 / 10 / 20 / 40 bps slippage per trade, always on top of the 5 bps fees. Guide for realism: typical one-way
slippage is about 1-2 bps for mega caps, 5-10 for mid caps, 10-20 for small caps, and a 1.5-2x stress is the
usual robustness bar. Several recent momentum picks (SNDK, LITE, ...) are mid-size, so 5 bps is optimistic for
part of the book. Paper trading measures the real number (`compare.py` fill slippage). Run: python -m analysis.cost_stress
"""
from __future__ import annotations

import pandas as pd

from analysis.common import REARMED_RULES, build_runs
from analysis.qqq_trend import trend_returns
from backtest import FEES, INIT_CASH, metrics, simulate
from data import BENCHMARK
from risk import run_with_risk

SLIPPAGE_BPS = (5, 10, 20, 40)


def turnover_per_year(pf, years: float) -> float:
    """Traded notional (buys + sells, so about twice the one-way turnover) per year, as a multiple of average equity.

    Costs are charged on every order, so cost drag per year is roughly this number times the per-trade cost."""
    orders = pf.orders.records_readable
    return float((orders["Size"] * orders["Price"]).sum() / pf.value().mean() / years)


def main() -> None:
    runs = build_runs()
    years = (runs.returns.index[-1] - runs.start).days / 365.25
    rows: dict[tuple[str, int], dict[str, float]] = {}
    for bps in SLIPPAGE_BPS:
        slip = bps / 1e4
        pf = simulate(runs.close, runs.weights, FEES, slip)
        orders = run_with_risk(runs.close, runs.weights, runs.groups, runs.bench, REARMED_RULES, FEES + slip, INIT_CASH).orders
        pf_risk = simulate(runs.close, orders, FEES, slip)
        r_trend, switches = trend_returns(runs.bench, runs.rf, 200, cost=FEES + slip)
        series = {
            "Momentum, no risk layer": pf.returns().loc[runs.start:],
            "Momentum + risk (re-armed)": pf_risk.returns().loc[runs.start:],
            "QQQ trend 200d": r_trend.loc[runs.start:],
        }
        for name, r in series.items():
            m = metrics(r, runs.rf)
            rows[(name, bps)] = {"CAGR": m["CAGR"], "Sharpe (excess)": m["Sharpe (excess)"],
                                 "Max drawdown": m["Max drawdown"], "$100k becomes": (1 + r).prod() * INIT_CASH}
        rows[("Momentum, no risk layer", bps)]["traded notional x/yr"] = turnover_per_year(pf, years)
        rows[("Momentum + risk (re-armed)", bps)]["traded notional x/yr"] = turnover_per_year(pf_risk, years)
        rows[("QQQ trend 200d", bps)]["traded notional x/yr"] = switches / years
    qqq = runs.returns[BENCHMARK]
    m = metrics(qqq, runs.rf)
    print(f"Sample {runs.start.date()}..{runs.returns.index[-1].date()}; fees 5 bps always; slippage varied; "
          f"QQQ buy-and-hold for reference: CAGR {m['CAGR']:.3f}, excess Sharpe {m['Sharpe (excess)']:.2f}, "
          f"${(1 + qqq).prod() * INIT_CASH:,.0f}\n")
    table = pd.DataFrame(rows).T
    table.index.names = ["strategy", "slippage bps"]
    print(table.round(3).to_string())
    print("\n(trend row of the last column = switches per year, each a full buy or sell, not notional multiples)")


if __name__ == "__main__":
    main()
