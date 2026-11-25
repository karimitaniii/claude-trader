"""Earnings-gap analysis behind the "hold through earnings" decision (2026-11-25).

Earnings dates come from yfinance (`get_earnings_dates`, cached in data_cache/earnings.csv). A name's
reaction day is the same day if it reported before the open, otherwise the next trading day.
Reports, for held names only: share of held days that are reaction days, mean return on those days
vs normal days, share of portfolio variance, and the "skip reaction days" counterfactual.

The counterfactual just removes held names' reaction-day returns (cash on those days). It ignores
the trading costs of stepping out and back in, so it is slightly generous to "exit". Weights are the
no-risk-layer momentum portfolio. Run: python -m analysis.earnings
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import yfinance as yf

from analysis.common import NO_RISK, build_runs
from backtest import metrics
from data import CACHE_DIR, KNOWN_NO_DATA

EARNINGS_FILE = CACHE_DIR / "earnings.csv"


def fetch_earnings(symbols: list[str], refresh: bool = False) -> pd.DataFrame:
    """Long frame (symbol, timestamp) of announcement times, cached. Empty result for a name = no data."""
    if EARNINGS_FILE.exists() and not refresh:
        return pd.read_csv(EARNINGS_FILE, parse_dates=["when"])
    rows = []
    for s in symbols:
        if s in KNOWN_NO_DATA:
            continue
        try:
            d = yf.Ticker(s).get_earnings_dates(limit=100)
        except Exception as e:  # network/API hiccup: skip the name, it shows up as missing coverage
            print(f"  {s}: {type(e).__name__}")
            continue
        if d is None or d.empty:
            continue
        idx = d.index.tz_convert("America/New_York")
        rows += [(s, t.tz_localize(None)) for t in idx]
        time.sleep(0.2)
    out = pd.DataFrame(rows, columns=["symbol", "when"]).drop_duplicates()
    if out.empty:
        raise RuntimeError("no earnings dates downloaded; not caching an empty file")
    CACHE_DIR.mkdir(exist_ok=True)
    out.to_csv(EARNINGS_FILE, index=False)
    return out


def reaction_mask(earn: pd.DataFrame, index: pd.DatetimeIndex, columns) -> pd.DataFrame:
    """Boolean date x symbol: True on the first trading day whose close reflects the announcement."""
    mask = pd.DataFrame(False, index=index, columns=list(columns))
    for sym, when in zip(earn["symbol"], earn["when"]):
        if sym not in mask.columns:
            continue
        day = when.normalize()
        after_close = when.hour >= 16
        pos = index.searchsorted(day, side="right" if after_close else "left")
        if pos < len(index):
            mask.iloc[pos, mask.columns.get_loc(sym)] = True
    return mask


def main() -> None:
    runs = build_runs()
    pf = runs.portfolios[NO_RISK]
    value = pf.value()
    w_end = pf.asset_value(group_by=False).div(value, axis=0)       # weights at each close
    w_prev = w_end.shift(1).loc[runs.start:]                         # weights held into each day
    rets = runs.close.pct_change().loc[runs.start:]

    earn = fetch_earnings(list(runs.close.columns))
    mask = reaction_mask(earn, runs.close.index, runs.close.columns).loc[runs.start:]
    held = w_prev > 1e-6
    react_held = held & mask
    print(f"Earnings rows: {len(earn)} across {earn['symbol'].nunique()} symbols")

    r = rets.fillna(0.0)
    contrib = (w_prev * r)
    on_react = contrib.where(react_held, 0.0).sum(axis=1)
    held_days = held.sum().sum()
    print(f"Reaction days = {react_held.sum().sum() / held_days:.1%} of held name-days")
    held_r = r.where(held)
    print(f"Mean held-name return: earnings reaction {held_r.where(react_held).stack().mean():+.2%}, "
          f"other days {held_r.where(~react_held).stack().mean():+.2%}")
    base = pf.returns().loc[runs.start:]
    print(f"Share of portfolio variance from reaction-day contributions (cov share): "
          f"{np.cov(on_react, base)[0, 1] / base.var():.1%}")

    exit_all = base - on_react
    half = base - 0.5 * on_react
    table = pd.DataFrame({"Hold through": metrics(base, runs.rf), "Skip reaction days": metrics(exit_all, runs.rf),
                          "Half size": metrics(half, runs.rf)})
    print(table.round(3).to_string())


if __name__ == "__main__":
    main()
