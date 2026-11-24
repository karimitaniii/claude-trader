import numpy as np
import pandas as pd
import pytest

from backtest import align_rf, metrics, sharpe


def test_excess_sharpe_subtracts_rf():
    idx = pd.bdate_range("2020-01-01", periods=500)
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.001, 0.01, len(idx)), index=idx)
    rf = pd.Series(0.0002, index=idx)
    expected = (r - 0.0002).mean() / (r - 0.0002).std() * np.sqrt(252)
    assert sharpe(r, rf) == pytest.approx(expected)
    assert sharpe(r, pd.Series(0.0, index=idx)) == pytest.approx(sharpe(r))
    assert sharpe(r, rf) < sharpe(r)


def test_align_rf_forward_fills_and_rejects_uncovered_start():
    rf = pd.Series([0.1, 0.2], index=pd.to_datetime(["2020-01-01", "2020-01-03"]))
    idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    assert align_rf(rf, idx).tolist() == [0.1, 0.2, 0.2]
    with pytest.raises(ValueError):
        align_rf(rf, pd.to_datetime(["2019-12-31"]))


def test_metrics_includes_excess_sharpe_only_with_rf():
    idx = pd.bdate_range("2020-01-01", periods=300)
    r = pd.Series(np.random.default_rng(2).normal(0.0005, 0.01, len(idx)), index=idx)
    assert "Sharpe (excess)" not in metrics(r)
    assert "Sharpe (excess)" in metrics(r, pd.Series(0.0001, index=idx))
