"""Volatility scaling of the top-N basket (tested 2026-11-25, NOT adopted; not used by live.py).

At each monthly rebalance, scale the target weights by min(1, TARGET_VOL / trailing 63d vol of the
basket), using only returns up to the signal day (weights are already shifted one bar). The
remainder sits in cash. No risk layer, costs on. Run: python -m analysis.vol_scaling
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.common import build_runs
from analysis.edge_test import bootstrap
from backtest import align_rf, metrics, simulate
from data import BENCHMARK

TARGET_VOL = 0.25
VOL_WINDOW = 63
TRADING_DAYS = 252


def scale_weights(close: pd.DataFrame, weights: pd.DataFrame, target: float = TARGET_VOL, window: int = VOL_WINDOW) -> pd.DataFrame:
    """Scale each rebalance row by min(1, target / trailing basket vol) known on the signal day."""
    rets = close.pct_change().fillna(0.0)  # unlisted names carry weight 0; NaN @ 0 would poison the dot product
    out = weights.copy()
    pos = {d: i for i, d in enumerate(close.index)}
    for day in weights.index[weights.notna().any(axis=1)]:
        i = pos[day]
        signal = i - 1  # the row trades on `day` but was decided at the previous close
        if signal < window:
            continue
        w = weights.iloc[i].fillna(0.0)
        basket = (rets.iloc[signal - window + 1 : signal + 1] @ w) / max(w.sum(), 1e-12)
        vol = basket.std() * np.sqrt(TRADING_DAYS)
        scale = min(1.0, target / vol) if vol > 0 else 1.0
        out.iloc[i] = weights.iloc[i] * scale
    return out


def main() -> None:
    runs = build_runs()
    scaled = scale_weights(runs.close, runs.weights)
    base = runs.returns.iloc[:, 0]
    vs = simulate(runs.close, scaled).returns().loc[runs.start:]
    qqq = runs.returns[BENCHMARK]
    table = pd.DataFrame({
        "Momentum": metrics(base, runs.rf),
        f"Vol-scaled ({TARGET_VOL:.0%})": metrics(vs, runs.rf),
        BENCHMARK: metrics(qqq, runs.rf),
    })
    print(table.round(3).to_string())
    for label, r in (("2020", slice("2020", "2020")), ("2022", slice("2022", "2022"))):
        print(f"{label} return: base {(1 + base.loc[r]).prod() - 1:+.2f}, scaled {(1 + vs.loc[r]).prod() - 1:+.2f}")
    rf = align_rf(runs.rf, base.index)
    ex = pd.DataFrame({"base": base - rf, "scaled": vs - rf})
    boot = bootstrap(ex)
    diff = boot["scaled"] - boot["base"]
    print(f"Paired Sharpe diff (scaled - base): CI [{np.percentile(diff, 2.5):.2f}, {np.percentile(diff, 97.5):.2f}], P>0 {(diff > 0).mean():.2f}")


if __name__ == "__main__":
    main()
