import numpy as np
import pandas as pd

from signals import equal_weights, target_weights


def synthetic_prices(n_days: int = 600, n_assets: int = 10, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n_days)
    rets = rng.normal(0.0005, 0.02, size=(n_days, n_assets))
    return pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=[f"S{i}" for i in range(n_assets)])


def test_rebalance_rows_are_fully_invested_top_n():
    w = target_weights(synthetic_prices(), top_n=4, lookback=126, skip=21)
    rows = w.dropna(how="all")
    assert len(rows) > 0
    np.testing.assert_allclose(rows.sum(axis=1), 1.0)
    assert ((rows > 0).sum(axis=1) == 4).all()


def test_trades_on_first_trading_day_after_month_end():
    close = synthetic_prices()
    w = target_weights(close, top_n=4, lookback=126, skip=21)
    month_ends = close.groupby(close.index.to_period("M")).tail(1).index
    for day in w.dropna(how="all").index:
        prev = close.index[close.index.get_loc(day) - 1]
        assert prev in month_ends


def test_no_look_ahead():
    """Changing prices after day t must not change any weight up to and including t+1."""
    close = synthetic_prices()
    # Choose t so that t+1 is a month-end signal day: an unshifted signal would leak there.
    month_ends = close.groupby(close.index.to_period("M")).tail(1).index
    t = close.index.get_loc(month_ends[month_ends > close.index[400]][0]) - 1
    shocked = close.copy()
    shocked.iloc[t + 1 :] *= np.linspace(0.2, 5.0, close.shape[1])
    a = target_weights(close, top_n=4, lookback=126, skip=0).iloc[: t + 2]
    b = target_weights(shocked, top_n=4, lookback=126, skip=0).iloc[: t + 2]
    pd.testing.assert_frame_equal(a, b)


def test_only_eligible_names_are_picked():
    close = synthetic_prices()
    eligible = pd.DataFrame(True, index=close.index, columns=close.columns)
    eligible.loc[:, ["S0", "S1", "S2"]] = False
    eligible.loc[close.index[450]:, "S0"] = True  # S0 joins the index later
    w = target_weights(close, top_n=3, lookback=126, skip=21, eligible=eligible)
    rows = w.dropna(how="all")
    signal_days = close.index[[close.index.get_loc(d) - 1 for d in rows.index]]
    for (day, row), sig in zip(rows.iterrows(), signal_days):
        picked = set(row[row > 0].index)
        assert not picked & {"S1", "S2"}
        if sig < close.index[450]:
            assert "S0" not in picked


def test_eligibility_uses_membership_on_signal_day_not_trade_day():
    """A name that leaves the index on the trade day (t+1) was still eligible at the signal close t."""
    close = synthetic_prices()
    base = target_weights(close, top_n=3, lookback=126, skip=21)
    day = base.dropna(how="all").index[5]  # a trade day (t+1)
    held = base.loc[day][base.loc[day] > 0].index[0]
    eligible = pd.DataFrame(True, index=close.index, columns=close.columns)
    eligible.loc[day:, held] = False  # removed effective on the trade day
    w = target_weights(close, top_n=3, lookback=126, skip=21, eligible=eligible)
    assert w.loc[day, held] > 0


def test_static_universe_unchanged_by_all_true_mask():
    close = synthetic_prices()
    eligible = pd.DataFrame(True, index=close.index, columns=close.columns)
    pd.testing.assert_frame_equal(
        target_weights(close, top_n=4, lookback=126, skip=21),
        target_weights(close, top_n=4, lookback=126, skip=21, eligible=eligible),
    )


def test_equal_weights_spreads_over_all_eligible_scored_names():
    close = synthetic_prices()
    eligible = pd.DataFrame(True, index=close.index, columns=close.columns)
    eligible.loc[:, "S9"] = False
    w = equal_weights(close, lookback=126, skip=21, eligible=eligible)
    rows = w.dropna(how="all")
    assert len(rows) > 0
    np.testing.assert_allclose(rows.drop(columns="S9").to_numpy(), 1 / 9)
    assert (rows["S9"] == 0).all()


def test_weekly_and_daily_rebalance_dates_and_no_look_ahead():
    close = synthetic_prices()
    week_ends = close.groupby(close.index.to_period("W")).tail(1).index
    w = target_weights(close, top_n=4, lookback=126, skip=21, freq="W")
    for day in w.dropna(how="all").index:
        assert close.index[close.index.get_loc(day) - 1] in week_ends
    d = target_weights(close, top_n=4, lookback=126, skip=21, freq="D")
    rows = d.dropna(how="all")
    assert len(rows) == len(close) - 126 - 1  # every day once the score exists, shifted 1 bar
    # changing today's price must not change today's (or earlier) weights
    bumped = close.copy()
    bumped.iloc[-1] *= 2
    pd.testing.assert_frame_equal(d, target_weights(bumped, top_n=4, lookback=126, skip=21, freq="D"))
