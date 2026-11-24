import inspect
import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import broker
import live
from broker import PaperSimBroker
from signals import target_weights, targets_from_signal_day


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(live, "LOG_DIR", tmp_path / "logs")


# ---------- pure helpers ----------

def test_completed_bars_drops_todays_partial_bar():
    idx = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    df = pd.DataFrame({"A": [1, 2, 3]}, index=idx)
    assert live.completed_bars(df, pd.Timestamp("2026-11-24")).index[-1] == pd.Timestamp("2026-11-23")


def test_previous_month_end_is_last_trading_day_of_prior_month():
    idx = pd.bdate_range("2026-10-20", "2026-11-24")
    assert live.previous_month_end(idx, pd.Timestamp("2026-11-24")) == pd.Timestamp("2026-10-30")


def test_live_targets_equal_backtest_row():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=400)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (400, 6)), axis=0)), index=idx, columns=list("ABCDEF"))
    bt = target_weights(close, top_n=3, lookback=126, skip=21)
    trade_day = bt.dropna(how="all").index[-1]
    signal_day = close.index[close.index.get_loc(trade_day) - 1]
    live_row = targets_from_signal_day(close, signal_day, top_n=3, lookback=126, skip=21)
    pd.testing.assert_series_equal(live_row, bt.loc[trade_day], check_names=False)


def test_plan_orders_whole_shares_sells_first_and_idempotent_ids():
    target = pd.Series({"A": 0.5, "B": 0.5})
    prices = pd.Series({"A": 100.0, "B": 30.0, "C": 50.0})
    orders = live.plan_orders(target, {"A": 100.0, "C": 10.0}, prices, 100_000.0, "20261124")
    by = {o.symbol: o for o in orders}
    assert orders[0].side == "sell"
    assert (by["A"].side, by["A"].qty) == ("buy", 400)      # 50k / 100 = 500 shares, hold 100
    assert (by["B"].side, by["B"].qty) == ("buy", 1666)     # floor(50k / 30)
    assert (by["C"].side, by["C"].qty) == ("sell", 10)      # not a target any more
    assert by["C"].client_order_id == "tm-20261124-C-sell"
    assert live.plan_orders(target, {"A": 100.0, "C": 10.0}, prices, 100_000.0, "20261124") == orders


def test_plan_orders_never_exceeds_equity():
    target = pd.Series({"A": 0.5, "B": 0.5})
    prices = pd.Series({"A": 333.0, "B": 77.7})
    orders = live.plan_orders(target, {}, prices, 10_000.0, "x")
    assert sum(o.qty * prices[o.symbol] for o in orders) <= 10_000.0


def test_plan_orders_refuses_target_without_price():
    with pytest.raises(ValueError):
        live.plan_orders(pd.Series({"A": 1.0}), {}, pd.Series({"A": np.nan}), 1000.0, "x")


# ---------- paper-only safety ----------

def test_broker_is_hardcoded_to_paper():
    src = inspect.getsource(broker.AlpacaPaperBroker.__init__)
    assert "paper=True" in src and "paper=False" not in src
    assert "paper=False" not in inspect.getsource(live)


def test_broker_refuses_without_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        broker.AlpacaPaperBroker()


# ---------- end-to-end run with a fake broker and synthetic data ----------

def fake_market(monkeypatch, n=400, crash=False):
    rng = np.random.default_rng(1)
    idx = pd.bdate_range(end="2026-11-24", periods=n)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.001, 0.015, (n, 6)), axis=0)), index=idx, columns=list("ABCDEF"))
    eligible = pd.DataFrame(True, index=idx, columns=close.columns)
    bench = pd.DataFrame({"QQQ": np.linspace(100, 200, n)}, index=idx)
    monkeypatch.setattr(live, "load_universe", lambda kind, refresh: (close, eligible))
    monkeypatch.setattr(live, "load_prices", lambda tickers, refresh: bench)
    monkeypatch.setattr(live, "symbol_groups", lambda syms: pd.Series("software", index=list(syms)))
    monkeypatch.setattr(live, "PARAMS", {"top_n": 3, "lookback": 126, "skip": 21})
    return close


def events(tmp_logs):
    return [json.loads(l) for f in sorted(tmp_logs.glob("*.jsonl")) for l in f.read_text().splitlines()]


def test_dry_run_plans_but_submits_nothing(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    live.run(b, submit=False, now=datetime(2026, 11, 24, 12, 0, tzinfo=live.ET))
    kinds = [e["kind"] for e in events(live.LOG_DIR)]
    assert "dry_run" in kinds and "order_submitted" not in kinds
    assert b.submitted == []
    assert json.loads(live.STATE_FILE.read_text())["last_rebalance_month"] is None


def test_submit_rebalances_once_per_month(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    when = datetime(2026, 11, 24, 12, 0, tzinfo=live.ET)
    live.run(b, submit=True, now=when)
    n = len(b.submitted)
    assert n == 3 and all(o.side == "buy" for o in b.submitted)
    live.run(b, submit=True, now=when)  # second run same month: nothing new
    assert len(b.submitted) == n
    assert "no_rebalance" in [e["kind"] for e in events(live.LOG_DIR)]


def test_kill_switch_liquidates_and_blocks_until_manual_reset(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker(equity=100_000.0, positions={"A": 10.0})
    live.run(b, submit=True, now=datetime(2026, 11, 23, 12, 0, tzinfo=live.ET))  # sets peak 100k
    b._equity = 70_000.0
    b.submitted.clear()
    live.run(b, submit=True, now=datetime(2026, 11, 24, 12, 0, tzinfo=live.ET))
    assert [(o.symbol, o.side) for o in b.submitted] == [("A", "sell")]
    log = events(live.LOG_DIR)
    assert any(e["kind"] == "alert" and "KILL SWITCH" in e["message"] for e in log)
    assert json.loads(live.STATE_FILE.read_text())["kill"]["killed"] is True


def test_stale_data_aborts_with_alert(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    live.run(b, submit=True, now=datetime(2026, 12, 15, 12, 0, tzinfo=live.ET))
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "stale" in e["message"] for e in events(live.LOG_DIR))
