import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import broker
import live
import trend_live
from broker import PaperSimBroker


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_live, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(trend_live, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(live, "LOG_DIR", tmp_path / "logs")


def fake_bench(monkeypatch, up=True, n=300):
    idx = pd.bdate_range(end="2026-11-24", periods=n)
    px = np.linspace(100, 200, n) if up else np.linspace(200, 100, n)
    monkeypatch.setattr(trend_live, "load_prices", lambda tickers, refresh: pd.DataFrame({"QQQ": px}, index=idx))


def events():
    return [json.loads(l) for f in sorted(trend_live.LOG_DIR.glob("*.jsonl")) for l in f.read_text().splitlines()]


WHEN = datetime(2026, 11, 24, 12, 0, tzinfo=live.ET)


def test_want_invested_follows_200d_average():
    up = pd.Series(np.linspace(100, 200, 300))
    assert trend_live.want_invested(up) and not trend_live.want_invested(up[::-1].reset_index(drop=True))


def test_plan_orders_only_on_state_change():
    assert trend_live.plan_trend_orders(True, {"QQQ": 100.0}, 500.0, 50_000.0, "20261124") == []
    assert trend_live.plan_trend_orders(False, {}, 500.0, 50_000.0, "20261124") == []
    buy = trend_live.plan_trend_orders(True, {}, 500.0, 50_000.0, "20261124")
    assert [(o.symbol, o.side, o.qty) for o in buy] == [("QQQ", "buy", 98)]   # 98% target: cash buffer
    assert buy[0].qty * 500.0 < 50_000.0
    sell = trend_live.plan_trend_orders(False, {"QQQ": 100.0}, 500.0, 50_000.0, "20261124")
    assert [(o.symbol, o.side, o.qty) for o in sell] == [("QQQ", "sell", 100)]


def test_dry_run_submits_nothing(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker()
    trend_live.run(b, submit=False, now=WHEN)
    assert b.submitted == [] and "dry_run" in [e["kind"] for e in events()]


def test_submit_buys_once_then_holds(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker()
    trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "buy")]
    b2 = PaperSimBroker(positions={"QQQ": 500.0})   # next day: position filled, still above trend
    trend_live.run(b2, submit=True, now=datetime(2026, 11, 25, 12, 0, tzinfo=live.ET))
    assert b2.submitted == []


def test_sells_when_trend_breaks(monkeypatch):
    fake_bench(monkeypatch, up=False)
    b = PaperSimBroker(positions={"QQQ": 500.0})
    trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "sell")]


def test_stray_positions_abort_with_alert(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker(positions={"NVDA": 10.0})
    trend_live.run(b, submit=True, now=WHEN)
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "unexpected positions" in e["message"] for e in events())


def test_kill_switch_liquidates(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker(equity=100_000.0, positions={"QQQ": 100.0})
    trend_live.run(b, submit=True, now=datetime(2026, 11, 23, 12, 0, tzinfo=live.ET))
    b._equity = 70_000.0
    b.submitted.clear()
    trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "sell")]
    assert json.loads(trend_live.STATE_FILE.read_text())["kill"]["killed"] is True


def test_broker_reads_named_env_vars(monkeypatch):
    monkeypatch.delenv("ALPACA_TREND_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_TREND_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ALPACA_TREND_API_KEY"):
        broker.AlpacaPaperBroker("ALPACA_TREND_API_KEY", "ALPACA_TREND_SECRET_KEY")


def test_second_run_same_day_does_not_resubmit(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker()   # the sim never fills, like an order still pending until the close
    trend_live.run(b, submit=True, now=WHEN)
    trend_live.run(b, submit=True, now=WHEN)
    assert len(b.submitted) == 1
    assert not any(e["kind"] == "error" for e in events())


def test_refuses_to_share_the_momentum_account(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "same-key")
    monkeypatch.setenv("ALPACA_TREND_API_KEY", "same-key")
    monkeypatch.setattr("sys.argv", ["trend_live.py"])
    with pytest.raises(SystemExit) as exc:
        trend_live.main()
    assert exc.value.code == 2
