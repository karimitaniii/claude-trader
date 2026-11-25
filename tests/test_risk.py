import numpy as np
import pandas as pd
import pytest

from risk import NO_LIMITS, KillSwitch, RiskLimits, apply_limits, run_with_risk, trend_ok

GROUPS = pd.Series({"A": "semis", "B": "semis", "C": "software", "D": "software"})


def w(**kw) -> pd.Series:
    return pd.Series({k: kw.get(k, 0.0) for k in "ABCD"})


# ---------- apply_limits ----------

def test_position_cap_clips_and_leaves_excess_in_cash():
    out, fired = apply_limits(w(A=0.4, C=0.3, D=0.3), GROUPS, RiskLimits(max_position=0.3, group_caps=()))
    assert out["A"] == pytest.approx(0.3)
    assert out.sum() == pytest.approx(0.9)
    assert any(f.startswith("position_cap") for f in fired)


def test_group_cap_scales_group_pro_rata():
    lim = RiskLimits(max_position=1.0, group_caps=(("semis", 0.5),))
    out, fired = apply_limits(w(A=0.45, B=0.30, C=0.25), GROUPS, lim)
    assert out["A"] + out["B"] == pytest.approx(0.5)
    assert out["A"] / out["B"] == pytest.approx(0.45 / 0.30)
    assert out["C"] == pytest.approx(0.25)
    assert any(f.startswith("group_cap") for f in fired)


def test_selloff_rule_only_when_trend_broken():
    lim = RiskLimits(max_position=1.0, group_caps=(), selloff_gross=0.5)
    target = w(A=0.25, B=0.25, C=0.25, D=0.25)
    on, _ = apply_limits(target, GROUPS, lim, trend_is_ok=True)
    off, fired = apply_limits(target, GROUPS, lim, trend_is_ok=False)
    assert on.sum() == pytest.approx(1.0)
    assert off.sum() == pytest.approx(0.5)
    assert any(f.startswith("selloff") for f in fired)


def test_gross_cap_and_long_only():
    out, _ = apply_limits(w(A=0.6, B=-0.2, C=0.6), GROUPS, RiskLimits(max_position=1.0, group_caps=(), max_gross=1.0))
    assert out["B"] == 0
    assert out.sum() == pytest.approx(1.0)


def test_limits_always_hold_for_random_targets():
    rng = np.random.default_rng(0)
    lim = RiskLimits()
    for _ in range(200):
        t = pd.Series(rng.uniform(-0.2, 0.6, 4), index=list("ABCD"))
        out, _ = apply_limits(t, GROUPS, lim, trend_is_ok=bool(rng.integers(2)))
        assert (out >= 0).all()
        assert (out <= lim.max_position + 1e-9).all()
        assert out[["A", "B"]].sum() <= 0.5 + 1e-9
        assert out.sum() <= lim.max_gross + 1e-9


def test_invalid_limits_rejected():
    with pytest.raises(ValueError):
        RiskLimits(max_position=1.5)


# ---------- trend ----------

def test_trend_ok_is_causal():
    s = pd.Series(np.r_[np.linspace(100, 120, 50), np.linspace(120, 60, 50)])
    a = trend_ok(s, 20)
    shocked = s.copy(); shocked.iloc[60:] = 1000.0
    pd.testing.assert_series_equal(a.iloc[:60], trend_ok(shocked, 20).iloc[:60])
    assert a.iloc[:19].all()  # no information yet -> no restriction


# ---------- kill switch ----------

def test_kill_switch_triggers_at_threshold_not_before():
    ks = KillSwitch(RiskLimits(kill_drawdown=0.25, kill_cooldown_days=3))
    assert ks.update(100.0, True) is None
    assert ks.update(76.0, True) is None
    assert ks.update(75.0, True) == "kill"
    assert ks.killed


def test_hard_stop_stays_killed_until_manual_reset():
    ks = KillSwitch(RiskLimits(kill_drawdown=0.25, kill_cooldown_days=3))
    ks.update(100.0, True); assert ks.update(70.0, True) == "kill"
    assert all(ks.update(200.0, True) is None for _ in range(500))  # never re-arms by itself
    assert ks.killed
    ks.reset(70.0)
    assert not ks.killed and ks.peak == 70.0


def test_auto_rearm_needs_cooldown_and_trend_then_resets_peak():
    ks = KillSwitch(RiskLimits(kill_drawdown=0.25, kill_cooldown_days=3, kill_manual_reset=False))
    ks.update(100.0, True); ks.update(70.0, True)
    assert [ks.update(70.0, True) for _ in range(2)] == [None, None]  # cooldown
    assert ks.update(70.0, False) is None                            # cooldown done, trend broken
    assert ks.update(70.0, True) == "rearm"
    assert ks.peak == 70.0
    assert ks.update(60.0, True) is None  # -14% from the new peak, not the old one


# ---------- run_with_risk ----------

def make_market(n=60, crash_at=30):
    idx = pd.bdate_range("2020-01-01", periods=n)
    a = np.r_[np.full(crash_at, 100.0), np.full(n - crash_at, 50.0)]  # A halves at crash_at
    close = pd.DataFrame({"A": a, "C": np.full(n, 100.0)}, index=idx)
    targets = pd.DataFrame(np.nan, index=idx, columns=close.columns)
    targets.iloc[[1, 40]] = [1.0, 0.0]  # strategy: all in A, and tries to buy again on day 40
    bench = pd.Series(100.0, index=idx)
    return close, targets, bench


def test_no_limits_passes_strategy_through_unchanged():
    close, targets, bench = make_market()
    run = run_with_risk(close, targets, pd.Series({"A": "x", "C": "y"}), bench, NO_LIMITS, cost_rate=0.0)
    pd.testing.assert_frame_equal(run.orders.dropna(how="all"), targets.dropna(how="all"))


def test_kill_switch_liquidates_next_day_and_overrides_strategy():
    close, targets, bench = make_market()
    lim = RiskLimits(max_position=1.0, group_caps=(), kill_drawdown=0.25, kill_cooldown_days=100)
    run = run_with_risk(close, targets, pd.Series({"A": "x", "C": "y"}), bench, lim, cost_rate=0.0)
    kill_day = run.events.loc[run.events["rule"] == "kill", "date"].item()
    assert kill_day == close.index[30]                      # decided at the crash close
    assert run.orders.loc[close.index[30]].isna().all()     # not traded the same day
    assert (run.orders.loc[close.index[31]] == 0).all()     # liquidated at the next close
    assert run.orders.loc[close.index[40]].isna().all()     # strategy's day-40 buy is blocked
    assert run.equity.iloc[-1] == pytest.approx(run.equity.iloc[31])  # in cash afterwards


def test_costs_are_charged_on_traded_notional():
    close, targets, bench = make_market(crash_at=60)
    run = run_with_risk(close, targets, pd.Series({"A": "x", "C": "y"}), bench, NO_LIMITS, cost_rate=0.001)
    assert run.equity.iloc[1] == pytest.approx(100_000 * (1 - 0.001))


def test_default_limits_cap_hardware_at_35pct():
    groups = pd.Series({"A": "semis", "B": "semis", "C": "hardware", "D": "hardware"})
    out, fired = apply_limits(w(A=0.25, B=0.25, C=0.25, D=0.25), groups, RiskLimits(max_position=1.0))
    assert abs(out[["C", "D"]].sum() - 0.35) < 1e-12
    assert abs(out[["A", "B"]].sum() - 0.50) < 1e-12
    assert any("hardware" in f for f in fired)
