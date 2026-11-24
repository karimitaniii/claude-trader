import numpy as np
import pandas as pd
import pytest

from walkforward import Fold, make_folds, param_grid, select_params, stitch_weights


def test_folds_train_strictly_before_test_and_tests_contiguous():
    folds = make_folds(pd.Timestamp("2014-02-03"), pd.Timestamp("2026-11-23"), train_years=3)
    assert folds[0].train_start == pd.Timestamp("2014-02-03")  # clipped to first date
    assert folds[0].test_start == pd.Timestamp("2017-01-01")
    assert folds[-1].test_end == pd.Timestamp("2026-11-23")  # clipped to last date
    for f in folds:
        assert f.train_start < f.train_end < f.test_start <= f.test_end
        assert f.test_start - f.train_end == pd.Timedelta(days=1)
    for a, b in zip(folds, folds[1:]):
        assert b.test_start - a.test_end == pd.Timedelta(days=1)


def test_select_params_ignores_data_after_train_window():
    idx = pd.bdate_range("2016-01-01", "2018-12-31")
    rng = np.random.default_rng(3)
    returns = {p: pd.Series(rng.normal(0.0005 * i, 0.01, len(idx)), index=idx) for i, p in enumerate(param_grid())}
    rf = pd.Series(0.0, index=idx)
    fold = Fold(pd.Timestamp("2016-01-01"), pd.Timestamp("2017-12-31"), pd.Timestamp("2018-01-01"), pd.Timestamp("2018-12-31"))
    chosen, score = select_params(returns, fold, rf)

    # Make a different combo spectacular in the test window only: choice must not change.
    other = next(p for p in returns if p != chosen)
    tampered = {p: r.copy() for p, r in returns.items()}
    tampered[other].loc["2018"] = 0.05
    assert select_params(tampered, fold, rf) == (chosen, pytest.approx(score))


def test_stitch_weights_uses_chosen_combo_per_fold():
    idx = pd.bdate_range("2017-01-02", "2018-12-31")
    cols = ["A", "B"]
    rebal = idx.to_series().groupby(idx.to_period("M")).head(1).index
    wa = pd.DataFrame(np.nan, index=idx, columns=cols); wa.loc[rebal] = [1.0, 0.0]
    wb = pd.DataFrame(np.nan, index=idx, columns=cols); wb.loc[rebal] = [0.0, 1.0]
    folds = [
        Fold(pd.Timestamp("2014-01-01"), pd.Timestamp("2016-12-31"), pd.Timestamp("2017-01-01"), pd.Timestamp("2017-12-31")),
        Fold(pd.Timestamp("2015-01-01"), pd.Timestamp("2017-12-31"), pd.Timestamp("2018-01-01"), pd.Timestamp("2018-12-31")),
    ]
    out = stitch_weights({(1, 0, 1): wa, (2, 0, 1): wb}, folds, [(1, 0, 1), (2, 0, 1)])
    assert (out.loc["2017"].dropna()["A"] == 1.0).all()
    assert (out.loc["2018"].dropna()["B"] == 1.0).all()


def test_stitch_weights_rejects_window_not_starting_on_rebalance():
    idx = pd.bdate_range("2017-01-02", "2017-12-29")
    w = pd.DataFrame(np.nan, index=idx, columns=["A"]); w.loc["2017-02-01"] = 1.0
    fold = Fold(pd.Timestamp("2014-01-01"), pd.Timestamp("2016-12-31"), pd.Timestamp("2017-01-01"), pd.Timestamp("2017-12-31"))
    with pytest.raises(ValueError):
        stitch_weights({(1, 0, 1): w}, [fold], [(1, 0, 1)])
