"""Is there an edge beyond leveraged QQQ?  (reproduces the 2026-11-25 DECISIONS.md entry)

1. Regress the strategy's daily excess return on QQQ's daily excess return, with Newey-West
   (Bartlett kernel) standard errors: alpha, beta, R^2, alpha t-stat.
2. Circular block bootstrap (21-day blocks) of the Sharpe ratio and of Sharpe differences.

Uses the no-risk-layer momentum returns, like the original analysis. Run: python -m analysis.edge_test
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.common import NO_RISK, build_runs
from backtest import align_rf
from data import BENCHMARK

TRADING_DAYS = 252


def newey_west_ols(y: np.ndarray, x: np.ndarray, lags: int = 10) -> dict[str, float]:
    """OLS of y on [1, x] with Newey-West HAC standard errors."""
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n = len(y)
    xe = X * resid[:, None]
    s = xe.T @ xe / n
    for lag in range(1, lags + 1):
        g = xe[lag:].T @ xe[:-lag] / n
        s += (1 - lag / (lags + 1)) * (g + g.T)
    bread = np.linalg.inv(X.T @ X / n)
    cov = bread @ s @ bread / n
    se = np.sqrt(np.diag(cov))
    r2 = 1 - resid.var() / y.var()
    return {"alpha_daily": beta[0], "beta": beta[1], "alpha_t": beta[0] / se[0], "beta_t": beta[1] / se[1], "r2": r2}


def block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """One circular block-bootstrap resample of range(n)."""
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, n_blocks)
    return ((starts[:, None] + np.arange(block)) % n).ravel()[:n]


def sharpe_np(r: np.ndarray) -> float:
    return r.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS)


def bootstrap(excess: pd.DataFrame, n_boot: int = 5000, block: int = 21, seed: int = 0) -> dict[str, np.ndarray]:
    """Paired bootstrap: the same resampled days are used for every column."""
    rng = np.random.default_rng(seed)
    arr = excess.to_numpy()
    out = np.empty((n_boot, arr.shape[1]))
    for b in range(n_boot):
        out[b] = [sharpe_np(c) for c in arr[block_indices(len(arr), block, rng)].T]
    return {c: out[:, i] for i, c in enumerate(excess.columns)}


def main() -> None:
    runs = build_runs()
    rets = runs.returns[[NO_RISK, BENCHMARK]].dropna()
    rf = align_rf(runs.rf, rets.index)
    excess = rets.sub(rf, axis=0)

    reg = newey_west_ols(excess[NO_RISK].to_numpy(), excess[BENCHMARK].to_numpy())
    print(f"Sample {rets.index[0].date()}..{rets.index[-1].date()} ({len(rets)} days), costs on")
    print(f"Regression on QQQ (Newey-West, 10 lags): alpha {reg['alpha_daily'] * TRADING_DAYS:+.1%}/yr "
          f"(t={reg['alpha_t']:.2f}), beta {reg['beta']:.2f}, R2 {reg['r2']:.2f}")

    boot = bootstrap(excess)
    for name in excess.columns:
        lo, hi = np.percentile(boot[name], [2.5, 97.5])
        print(f"Sharpe {name:<26} point {sharpe_np(excess[name].to_numpy()):.2f}  95% CI [{lo:.2f}, {hi:.2f}]")
    diff = boot[NO_RISK] - boot[BENCHMARK]
    print(f"P(momentum Sharpe > QQQ Sharpe) = {(diff > 0).mean():.2f}; "
          f"diff CI [{np.percentile(diff, 2.5):.2f}, {np.percentile(diff, 97.5):.2f}]")


if __name__ == "__main__":
    main()
