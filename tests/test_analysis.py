"""Unit tests for the analysis helpers (no network, no vectorbt portfolios)."""
import numpy as np
import pandas as pd

from analysis.earnings import reaction_mask
from analysis.edge_test import block_indices, newey_west_ols
from analysis.vol_scaling import scale_weights


def test_newey_west_recovers_alpha_beta():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.01, 4000)
    y = 0.0004 + 1.5 * x + rng.normal(0, 0.002, 4000)
    out = newey_west_ols(y, x)
    assert abs(out["beta"] - 1.5) < 0.05
    assert abs(out["alpha_daily"] - 0.0004) < 0.0001
    assert out["r2"] > 0.9


def test_block_indices_shape_and_range():
    idx = block_indices(100, 21, np.random.default_rng(0))
    assert len(idx) == 100 and idx.min() >= 0 and idx.max() < 100


def test_reaction_mask_before_and_after_close():
    index = pd.bdate_range("2024-01-01", periods=10)
    earn = pd.DataFrame({
        "symbol": ["A", "B"],
        "when": [pd.Timestamp("2024-01-03 16:30"), pd.Timestamp("2024-01-04 07:00")],
    })
    m = reaction_mask(earn, index, ["A", "B"])
    assert m.loc["2024-01-04", "A"] and not m.loc["2024-01-03", "A"]   # after close -> next day
    assert m.loc["2024-01-04", "B"] and not m.loc["2024-01-03", "B"]   # before open -> same day


def test_scale_weights_only_reduces_and_uses_past_data():
    n = 200
    idx = pd.bdate_range("2023-01-02", periods=n)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0, 0.03, (n, 2)), axis=0), index=idx, columns=["X", "Y"])
    w = pd.DataFrame(np.nan, index=idx, columns=close.columns)
    w.iloc[150] = [0.5, 0.5]
    scaled = scale_weights(close, w, target=0.10)
    assert scaled.iloc[150].sum() < 1.0 - 1e-9
    assert (scaled.iloc[150] <= w.iloc[150] + 1e-12).all()
    # changing the trade day's own return must not change the scale (no look-ahead)
    close2 = close.copy()
    close2.iloc[150:] *= 3
    assert np.allclose(scale_weights(close2, w, target=0.10).iloc[150], scaled.iloc[150])


def test_tech_intervals_all_keeps_non_tech():
    from universe import tech_intervals

    iv = pd.DataFrame({"ticker": ["AAA", "BBB"], "start": pd.to_datetime(["2020-01-01"] * 2), "end": [pd.NaT] * 2})
    sm = pd.DataFrame({"ticker": ["AAA", "BBB"], "category": ["software", "non_tech"], "tech_like": [1, 0], "note": ["", ""]})
    assert list(tech_intervals(iv, sm)["ticker"]) == ["AAA"]
    assert list(tech_intervals(iv, sm, tech_only=False)["ticker"]) == ["AAA", "BBB"]


def test_trend_returns_no_lookahead_and_costs():
    from analysis.qqq_trend import COST, trend_returns

    idx = pd.bdate_range("2023-01-02", periods=60)
    px = pd.Series(100.0, index=idx)
    px.iloc[40:] = 50.0                      # crash on day 40: stays below the 30d average through day 59
    rf = pd.Series(0.0, index=idx)
    r, switches = trend_returns(px, rf, window=30)
    assert r.iloc[40] == px.pct_change().iloc[40]   # still fully invested on the crash day (decided at close of 39)
    assert switches == 1
    assert r.iloc[41] == -COST                       # exit trade on day 41 pays one-way cost, then flat in cash
    assert (r.iloc[42:] == 0).all()
