"""Does an IBD-style distribution-day count add anything to the 200-day trend rule?

A distribution day is a day QQQ closes down at least 0.2% on higher volume than the day before. The count is
over the trailing 25 sessions. Rule set BEFORE looking at results (standard IBD convention): out of QQQ when the
count is >= 5. Thresholds 4 and 6 are reported as sensitivity only, not as candidates.

Variants (all QQQ-only overlays; signal from close t trades at close t+1, costs on, cash earns T-bills):
  buy and hold | 200d trend | distribution count < 5 | both (trend ok AND count < 5)
Also a signal-level table: QQQ's forward 21-day return and volatility by signal state.
Integrating a filter into the momentum risk layer would need a change to `risk.py`; this only measures the
signal. Run: python -m analysis.distribution
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

from analysis.common import NO_RISK, REARMED, build_runs, completed_bars
from analysis.edge_test import newey_west_ols
from analysis.qqq_trend import overlay_returns
from backtest import align_rf, metrics
from data import BENCHMARK, CACHE_DIR
from risk import trend_ok

TRADING_DAYS = 252
DROP, WINDOW, THRESHOLD = 0.002, 25, 5


def load_volume(ticker: str = BENCHMARK, refresh: bool = False) -> pd.Series:
    """Daily volume, cached in data_cache/."""
    path = CACHE_DIR / f"{ticker.lower()}_volume.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    CACHE_DIR.mkdir(exist_ok=True)
    raw = yf.download(ticker, start="2013-01-01", auto_adjust=True, progress=False)
    vol = raw["Volume"].squeeze().dropna().rename("volume")
    if vol.empty:
        raise RuntimeError(f"no volume downloaded for {ticker}")
    vol.to_csv(path)
    return vol


def distribution_days(close: pd.Series, volume: pd.Series, drop: float = DROP) -> pd.Series:
    """True on days the close fell at least `drop` on higher volume than the previous session."""
    volume = volume.reindex(close.index)
    return ((close.pct_change() <= -drop) & (volume > volume.shift(1))).fillna(False)


def distribution_count(close: pd.Series, volume: pd.Series, window: int = WINDOW) -> pd.Series:
    """Number of distribution days in the trailing `window` sessions (uses data to t only)."""
    return distribution_days(close, volume).astype(int).rolling(window, min_periods=1).sum()


def forward_table(bench: pd.Series, states: dict[str, pd.Series], horizon: int = 21) -> pd.DataFrame:
    """QQQ's forward `horizon`-day return by signal state at the close (no trading lag; information content only)."""
    fwd = bench.shift(-horizon) / bench - 1
    rows = {}
    for name, bad in states.items():
        for label, mask in (("ok", ~bad), ("warning", bad)):
            f = fwd[mask].dropna()
            rows[(name, label)] = {"days %": mask.mean(), "mean fwd 21d": f.mean(), "worst fwd 21d": f.min(),
                                   "fwd vol (ann.)": (bench.pct_change().shift(-1)[mask].std() * np.sqrt(TRADING_DAYS))}
    return pd.DataFrame(rows).T


def main() -> None:
    runs = build_runs()
    bench = runs.bench
    vol = completed_bars(load_volume())
    count = distribution_count(bench, vol)
    trend = trend_ok(bench, 200)
    dist_ok = count < THRESHOLD

    variants = {"dist < 5": dist_ok, "trend 200d": trend, "trend AND dist < 5": trend & dist_ok}
    for t in (4, 6):
        variants[f"dist < {t} (sensitivity)"] = count < t
    cols = {NO_RISK: runs.returns[NO_RISK], REARMED: runs.returns[REARMED], BENCHMARK: runs.returns[BENCHMARK]}
    switches = {}
    for name, on in variants.items():
        r, n = overlay_returns(bench, on, runs.rf)
        cols[name], switches[name] = r.loc[runs.start:], n
    rets = pd.DataFrame(cols)

    print(f"Sample {runs.start.date()}..{rets.index[-1].date()}, costs on, cash earns T-bills")
    print(f"Distribution days: {int(distribution_days(bench, vol).sum())} in the history; count >= 5 on "
          f"{(~dist_ok).loc[runs.start:].mean():.1%} of days; below 200d on {(~trend).loc[runs.start:].mean():.1%}\n")
    table = rets.apply(lambda s: metrics(s, runs.rf))
    table.loc["2022 return"] = rets.loc["2022"].add(1).prod() - 1
    table.loc["End value of $100k"] = (1 + rets).prod() * 100_000
    print(table.round(3).to_string())
    print("\nSwitches:", switches)

    exc = rets.sub(align_rf(runs.rf, rets.index), axis=0)
    print("\nRegression on QQQ (alpha/yr, Newey-West t, beta):")
    for c in rets.columns:
        if c != BENCHMARK:
            reg = newey_west_ols(exc[c].to_numpy(), exc[BENCHMARK].to_numpy())
            print(f"  {c:<26} {reg['alpha_daily'] * TRADING_DAYS:+.1%}  t={reg['alpha_t']:.2f}  beta {reg['beta']:.2f}")

    states = {"below 200d": ~trend, "dist >= 5": ~dist_ok}
    sub = slice(runs.start, None)
    print("\nQQQ forward 21-day return by signal state (information content, no trading lag):")
    print(forward_table(bench.loc[sub], {k: v.loc[sub] for k, v in states.items()}).round(3).to_string())
    both = (~trend) & (~dist_ok)
    print(f"\nWarning episodes: dist>=5 starts {int(((~dist_ok) & dist_ok.shift(1, fill_value=True)).loc[sub].sum())}, "
          f"below-200d starts {int(((~trend) & trend.shift(1, fill_value=True)).loc[sub].sum())}; "
          f"both warnings at once on {both.loc[sub].mean():.1%} of days")


if __name__ == "__main__":
    main()
