"""Perturbation ("shock") tests for look-ahead: change prices from some close onward and check that nothing
decided or held BEFORE that point moves. Unlike a unit test of one shift, these fail for any timing mistake in the
chain, e.g. a signal traded at the same close that produced it."""
import numpy as np
import pandas as pd

from analysis.qqq_trend import positions
from risk import RiskLimits, run_with_risk, trend_ok


def rising_bench(n=400, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.Series(100 * np.cumprod(1 + 0.001 + rng.normal(0, 0.004, n)), index=idx)


def test_trend_position_through_day_t_ignores_closes_from_t_minus_1():
    bench = rising_bench()
    window = 50
    _, held = positions(trend_ok(bench, window))
    buggy_differs = False
    for t in (120, 200, 301):
        shocked = bench.copy()
        shocked.iloc[t - 1:] *= 0.3                      # crash from close t-1 on: below the average
        _, held_shocked = positions(trend_ok(shocked, window))
        # entered at close t-1 on the signal from close t-2: the t-1 crash cannot have influenced day t's position
        pd.testing.assert_series_equal(held.iloc[: t + 1], held_shocked.iloc[: t + 1])
        # negative control: a 1-bar lag (trading the signal at the close that produced it) WOULD leak here
        on, on_shocked = trend_ok(bench, window), trend_ok(shocked, window)
        buggy_differs |= not on.shift(1).fillna(True).iloc[: t + 1].equals(on_shocked.shift(1).fillna(True).iloc[: t + 1])
    assert buggy_differs, "the shock never flipped the signal, so this test could not detect a 1-bar lag"


def test_risk_layer_orders_ignore_prices_from_the_order_day_onward():
    rng = np.random.default_rng(3)
    n = 300
    idx = pd.bdate_range("2021-01-04", periods=n)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.0005, 0.02, (n, 3)), axis=0), index=idx, columns=list("ABC"))
    bench = rising_bench(n, seed=5).set_axis(idx)
    targets = pd.DataFrame(np.nan, index=idx, columns=close.columns)
    targets.iloc[5::10] = [0.4, 0.4, 0.2]
    groups = pd.Series({"A": "x", "B": "x", "C": "y"})
    limits = RiskLimits(max_position=0.35, group_caps=(("x", 0.6),), trend_window=40, selloff_gross=0.5,
                        kill_drawdown=0.2, kill_cooldown_days=5, kill_manual_reset=False)
    base = run_with_risk(close, targets, groups, bench, limits, cost_rate=0.001).orders
    for p in (60, 95, 150, 215):
        shocked_close, shocked_bench = close.copy(), bench.copy()
        shocked_close.iloc[p:] *= np.array([0.3, 1.5, 0.5])   # prices from day p onward move violently
        shocked_bench.iloc[p:] *= 0.4                         # and the benchmark falls below its trend
        shocked = run_with_risk(shocked_close, targets, groups, shocked_bench, limits, cost_rate=0.001).orders
        # the order placed at close p is decided from closes up to p-1 only
        pd.testing.assert_frame_equal(base.iloc[: p + 1], shocked.iloc[: p + 1])
