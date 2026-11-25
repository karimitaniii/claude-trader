"""Backtest: monthly-rebalanced momentum vs. an equal-weight universe and QQQ, with costs.

Runs both the point-in-time (PIT) universe and the old static list for comparison.
"""
from dataclasses import replace

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import vectorbt as vbt

from data import BENCHMARK, load_prices, load_risk_free
from signals import equal_weights, target_weights
from risk import NO_LIMITS, RiskLimits, run_with_risk
from universe import load_universe, symbol_groups

FEES = 0.0005       # 5 bps per trade (commission/regulatory; adjust to your broker)
SLIPPAGE = 0.0005   # 5 bps assumed slippage/spread cost
INIT_CASH = 100_000

PERIODS = {
    "Full sample": (None, None),
    "2014-2019": ("2014-01-01", "2019-12-31"),
    "2020-today": ("2020-01-01", None),
    "2022 (drawdown year)": ("2022-01-01", "2022-12-31"),
}


def simulate(close: pd.DataFrame, weights: pd.DataFrame, fees: float = FEES, slippage: float = SLIPPAGE) -> vbt.Portfolio:
    """Trade target weights (NaN = no order) at the close, with fees and slippage always on.

    `fees` / `slippage` can be raised for cost stress tests; they default to the project assumptions."""
    return vbt.Portfolio.from_orders(
        close=close,
        size=weights,
        size_type="targetpercent",
        fees=fees,
        slippage=slippage,
        init_cash=INIT_CASH,
        cash_sharing=True,
        group_by=True,
        call_seq="auto",  # sells execute before buys so cash is available
        freq="1D",
    )


def align_rf(rf: pd.Series, index: pd.Index) -> pd.Series:
    """Align a daily risk-free series to a return index (forward-fill holidays/gaps)."""
    out = rf.reindex(rf.index.union(index)).ffill().reindex(index)
    if out.isna().any():
        raise ValueError("risk-free series does not cover the start of the return series")
    return out


def sharpe(returns: pd.Series, rf: pd.Series | None = None, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio; net of the risk-free rate when `rf` is given."""
    r = returns.dropna()
    if rf is not None:
        r = r - align_rf(rf, r.index)
    std = r.std()
    return r.mean() / std * np.sqrt(periods_per_year) if std > 0 else np.nan


def metrics(
    returns: pd.Series, rf: pd.Series | None = None, periods_per_year: int = 252
) -> pd.Series:
    r = returns.dropna()
    equity = (1 + r).cumprod()
    years = len(r) / periods_per_year
    out = {
        "CAGR": equity.iloc[-1] ** (1 / years) - 1,
        "Volatility": r.std() * np.sqrt(periods_per_year),
        "Sharpe (raw)": sharpe(r, None, periods_per_year),
    }
    if rf is not None:
        out["Sharpe (excess)"] = sharpe(r, rf, periods_per_year)
    out["Max drawdown"] = (equity / equity.cummax() - 1).min()
    return pd.Series(out)


def strategy_returns(
    universe: str, top_n: int = 8, lookback: int = 252, skip: int = 21
) -> tuple[pd.Series, pd.Series, vbt.Portfolio]:
    """(momentum returns, equal-weight-universe returns, momentum portfolio) for one universe."""
    stocks, eligible = load_universe(universe)
    weights = target_weights(stocks, top_n=top_n, lookback=lookback, skip=skip, eligible=eligible)
    pf = simulate(stocks, weights)
    ew = simulate(stocks, equal_weights(stocks, lookback=lookback, skip=skip, eligible=eligible))
    start = weights.first_valid_index()
    return pf.returns().loc[start:], ew.returns().loc[start:], pf


def run(top_n: int = 8, lookback: int = 252, skip: int = 21) -> None:
    bench = load_prices([BENCHMARK])[BENCHMARK].ffill()
    rf = load_risk_free()

    mom_pit, ew_pit, pf_pit = strategy_returns("pit", top_n, lookback, skip)
    mom_static, ew_static, pf_static = strategy_returns("static", top_n, lookback, skip)
    start = max(mom_pit.index[0], mom_static.index[0])
    returns = {
        "Momentum PIT": mom_pit,
        "EW PIT": ew_pit,
        "Momentum static": mom_static,
        "EW static": ew_static,
        BENCHMARK: bench.pct_change(),
    }
    returns = {k: r.loc[start:] for k, r in returns.items()}

    print("PIT = point-in-time Nasdaq-100 tech-like members; static = old hand-picked 24 names")
    print(f"Trading starts {start.date()} | orders placed: PIT {pf_pit.orders.count()}, static {pf_static.orders.count()}")
    print(f"Risk-free: 13w T-bill (^IRX), mean {rf.loc[start:].mean() * 252:.2%}/yr over the sample")
    for name, (a, b) in PERIODS.items():
        table = pd.DataFrame({k: metrics(r.loc[a:b], rf) for k, r in returns.items()})
        print(f"\n=== {name} ===")
        print(table.round(3).to_string())

    curves = pd.DataFrame({k: (1 + r).cumprod() for k, r in returns.items()})
    curves.plot(logy=True, title="Growth of $1 (log scale, after costs)")
    plt.tight_layout()
    plt.savefig("equity_curves.png", dpi=150)
    print("\nSaved equity_curves.png")

    risk_report(top_n, lookback, skip, bench, rf)


RISK_VARIANTS: dict[str, RiskLimits] = {
    "No risk layer": NO_LIMITS,
    "Position cap 15%": replace(NO_LIMITS, max_position=0.15),
    "Semis cap 50%": replace(NO_LIMITS, group_caps=(("semis", 0.50),)),
    "Sell-off rule": replace(NO_LIMITS, selloff_gross=0.50),
    "Kill switch 25% (hard stop)": replace(NO_LIMITS, kill_drawdown=0.25),
    "Kill switch 25% (auto re-arm)": replace(NO_LIMITS, kill_drawdown=0.25, kill_manual_reset=False),
    "All (defaults)": RiskLimits(),
}


def risk_report(top_n: int, lookback: int, skip: int, bench: pd.Series, rf: pd.Series) -> None:
    """Momentum PIT with each risk rule alone and all together. Defaults are a priori, not tuned."""
    stocks, eligible = load_universe("pit")
    groups = symbol_groups(stocks.columns)
    weights = target_weights(stocks, top_n=top_n, lookback=lookback, skip=skip, eligible=eligible)
    start = weights.first_valid_index()

    rows, curves, runs = {}, {}, {}
    for name, limits in RISK_VARIANTS.items():
        run = run_with_risk(stocks, weights, groups, bench, limits, FEES + SLIPPAGE, INIT_CASH)
        pf = simulate(stocks, run.orders)  # official numbers come from vectorbt
        r = pf.returns().loc[start:]
        gross = (pf.asset_value(group_by=False).sum(axis=1) / pf.value()).loc[start:]
        m = metrics(r, rf)
        rows[name] = {
            "CAGR": m["CAGR"],
            "Sharpe (excess)": m["Sharpe (excess)"],
            "Max drawdown": m["Max drawdown"],
            "2022 return": (1 + r.loc["2022"]).prod() - 1,
            "2026 YTD": (1 + r.loc["2026"]).prod() - 1,
            "Avg gross": gross.mean(),
            "Kill events": int((run.events["rule"] == "kill").sum()) if len(run.events) else 0,
        }
        curves[name], runs[name] = (1 + r).cumprod(), run

    print(f"\n=== Risk layer on Momentum PIT ({start.date()}..), each rule alone vs all ===")
    print(pd.DataFrame(rows).round(3).to_string())

    ev = runs["All (defaults)"].events
    print("\nAll (defaults): rule firings at rebalances:", ev["rule"].value_counts().to_dict())
    print(ev[ev["rule"].isin(["kill", "liquidate", "rearm"])].to_string(index=False))

    curves[BENCHMARK] = (1 + bench.pct_change().loc[start:]).cumprod()
    pd.DataFrame(curves)[["No risk layer", "All (defaults)", BENCHMARK]].plot(
        logy=True, title="Momentum PIT with and without risk layer (log, after costs)"
    )
    plt.tight_layout()
    plt.savefig("risk_equity.png", dpi=150)
    print("\nSaved risk_equity.png")


if __name__ == "__main__":
    run()
