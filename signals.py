"""Signal layer: cross-sectional momentum -> target portfolio weights."""
from __future__ import annotations

import numpy as np
import pandas as pd


def momentum(close: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """12-1 momentum: return over ~12 months, skipping the most recent month."""
    return close.shift(skip) / close.shift(lookback) - 1


def eligible_scores(
    close: pd.DataFrame, lookback: int, skip: int, eligible: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Momentum, set to NaN wherever a name is not in the universe on that date.

    `eligible` is a boolean date x ticker frame (point-in-time membership at the close of
    each date). None means every column is always eligible (static universe).
    """
    mom = momentum(close, lookback, skip)
    if eligible is not None:
        mask = eligible.reindex(index=close.index, columns=close.columns, fill_value=False)
        mom = mom.where(mask.astype(bool))
    return mom


def _monthly(
    close: pd.DataFrame, scores: pd.DataFrame, top_n: int | None, freq: str = "M"
) -> pd.DataFrame:
    """Equal-weight the top_n scored names (all scored names if top_n is None) on the last trading
    day of each period ("M" month, "W" week, "D" every day), shifted one bar so the signal from
    day t's close trades on day t+1."""
    if freq == "D":
        rebalance_days = close.index
    else:
        rebalance_days = close.groupby(close.index.to_period(freq)).tail(1).index
    weights = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for day in rebalance_days:
        picked = _pick(scores.loc[day], top_n)
        if picked is not None:
            weights.loc[day] = picked
    return weights.shift(1)


def _pick(row: pd.Series, top_n: int | None) -> pd.Series | None:
    """Equal weights over the top_n scored names in one row; None if not enough names."""
    valid = row.dropna()
    n = len(valid) if top_n is None else top_n
    if n == 0 or len(valid) < n:
        return None  # not enough history / members yet
    out = pd.Series(0.0, index=row.index)
    out[valid.nlargest(n).index] = 1.0 / n
    return out


def targets_from_signal_day(
    close: pd.DataFrame,
    signal_day: pd.Timestamp,
    top_n: int = 8,
    lookback: int = 252,
    skip: int = 21,
    eligible: pd.DataFrame | None = None,
) -> pd.Series | None:
    """Target weights decided at `signal_day`'s close (to trade at the next close).

    Same logic as one row of `target_weights`; used by live trading, where the trade day
    is not in the data yet.
    """
    return _pick(eligible_scores(close, lookback, skip, eligible).loc[signal_day], top_n)


def target_weights(
    close: pd.DataFrame,
    top_n: int = 8,
    lookback: int = 252,
    skip: int = 21,
    eligible: pd.DataFrame | None = None,
    freq: str = "M",
) -> pd.DataFrame:
    """Equal-weight the top_n momentum names on the last trading day of each month
    (or week/day, see `freq`).

    Returns a DataFrame that is NaN except on rebalance rows (NaN = "no order").
    The weights are shifted by one bar: the signal is computed from the close on
    day t and traded on day t+1, so there is no look-ahead. Only names eligible on
    day t (point-in-time membership) can be picked.
    """
    return _monthly(close, eligible_scores(close, lookback, skip, eligible), top_n, freq)


def equal_weights(
    close: pd.DataFrame,
    lookback: int = 252,
    skip: int = 21,
    eligible: pd.DataFrame | None = None,
    freq: str = "M",
) -> pd.DataFrame:
    """Benchmark: equal-weight every name the momentum strategy could have picked
    (eligible and with a valid score), on the same dates. Same universe, no selection."""
    return _monthly(close, eligible_scores(close, lookback, skip, eligible), None, freq)
