import json

import pandas as pd
import pytest

import compare


def test_read_events_and_live_equity(tmp_path):
    lines = [
        {"kind": "account", "last_bar": "2026-12-01", "last_close_equity": 100000.0},
        {"kind": "account", "last_bar": "2026-12-02", "last_close_equity": 101000.0},
        {"kind": "account", "last_bar": "2026-12-02", "last_close_equity": 101000.0},  # second run same day
    ]
    (tmp_path / "2026-12-03.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    eq = compare.live_equity(compare.read_events(tmp_path))
    assert eq.to_dict() == {pd.Timestamp("2026-12-01"): 100000.0, pd.Timestamp("2026-12-02"): 101000.0}


def test_fill_slippage_sign_buy_and_sell():
    close = pd.DataFrame({"A": [100.0], "B": [50.0]}, index=pd.to_datetime(["2026-12-01"]))
    events = [
        {"kind": "fill", "client_order_id": "tm-20261201-A-buy", "symbol": "A", "side": "buy",
         "filled_qty": 10, "filled_avg_price": 100.10},
        {"kind": "fill", "client_order_id": "tm-20261201-B-sell", "symbol": "B", "side": "sell",
         "filled_qty": 5, "filled_avg_price": 49.95},
        {"kind": "order_final", "client_order_id": "tm-20261201-C-buy"},
    ]
    s = compare.fill_slippage(events, close).set_index("symbol")["slippage_bps"]
    assert s["A"] == pytest.approx(10.0)   # paid 10 bps above close
    assert s["B"] == pytest.approx(10.0)   # sold 10 bps below close: also a cost
    assert len(s) == 2


def test_trade_date_from_order_id_with_kill_suffix():
    assert compare.trade_date("tm-20261201-MU-kill") == pd.Timestamp("2026-12-01")


def _bench(values, start="2026-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_shadow_trend_equity_buys_at_close_after_signal_and_takes_next_day_move():
    # flat 100 for 60 days, -50% on day 50, a further -20% on day 51 (window 30: below the average from day 50)
    px = _bench([100.0] * 50 + [50.0] + [40.0] * 9)
    start = px.index[35]
    eq = compare.shadow_trend_equity(px, start, 100_000.0, window=30, target_weight=0.98, cost_rate=0.001)
    cost_in = 100_000.0 * (1 - 0.98 * 0.001)
    assert eq.iloc[0] == pytest.approx(cost_in)                      # bought at the close of `start`
    assert eq.loc[px.index[49]] == pytest.approx(cost_in)            # flat until the crash
    crash = cost_in * (1 - 0.98 * 0.5)                               # day 50: invested through the -50%
    assert eq.loc[px.index[50]] == pytest.approx(crash)
    # signal fired at close 50, the sell fills at close 51: day 51's -20% is still taken, then the exit costs
    w = 0.98 * 0.5 / (1 - 0.98 * 0.5)                                # QQQ share of equity after the crash
    after = crash * (1 + w * (-0.2))
    w2 = w * 0.8 / (1 + w * -0.2)
    assert eq.loc[px.index[51]] == pytest.approx(after * (1 - w2 * 0.001))
    assert eq.iloc[-1] == pytest.approx(eq.loc[px.index[51]])        # in cash afterwards


def test_shadow_trend_equity_stays_invested_without_churn():
    px = _bench([100.0 * 1.001 ** i for i in range(120)])
    start = px.index[40]
    eq = compare.shadow_trend_equity(px, start, 100_000.0, window=30, target_weight=0.98, cost_rate=0.001)
    # one buy only (no re-trading while the state is unchanged): 2% cash plus 98% riding with QQQ
    v0 = 100_000.0 * (1 - 0.98 * 0.001)
    expected = 0.02 * v0 + 0.98 * v0 * px.iloc[-1] / px.loc[start]
    assert eq.iloc[-1] == pytest.approx(expected)


def test_head_to_head_rebases_to_first_common_date():
    a = pd.Series([100.0, 110.0, 99.0], index=pd.bdate_range("2026-12-01", periods=3))
    b = pd.Series([200.0, 210.0], index=pd.bdate_range("2026-12-02", periods=2))
    out = compare.head_to_head(a, b, ("a", "b"))
    assert out.attrs["start"] == pd.Timestamp("2026-12-02")
    assert out.loc["a", "return"] == pytest.approx(99.0 / 110.0 - 1)
    assert out.loc["b", "return"] == pytest.approx(0.05)
    assert out.loc["a", "max drawdown"] == pytest.approx(99.0 / 110.0 - 1)
