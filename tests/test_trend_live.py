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


KILLED = {"last_kill_check": None, "last_submit_day": None, "logged_orders": [],
          "kill": {"peak": 100_000.0, "killed": False, "days_killed": 0}}


def down(*args, **kwargs):
    raise ConnectionError("down")


@pytest.mark.parametrize("failing", ["prices", "order history"])
def test_kill_switch_liquidates_even_when_a_data_source_is_down(monkeypatch, failing):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions={"QQQ": 100.0})
    if failing == "prices":
        monkeypatch.setattr(trend_live, "load_prices", down)
    else:
        b.orders_since = down
    with pytest.raises(ConnectionError):
        trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "sell")]


def test_active_kill_switch_alerts_on_every_run(monkeypatch):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0)
    trend_live.run(b, submit=False, now=WHEN)
    trend_live.run(b, submit=False, now=WHEN)
    assert sum(e["kind"] == "alert" and "KILL SWITCH" in e["message"] for e in events()) == 2


@pytest.mark.parametrize("n", [60, 0])
def test_short_benchmark_aborts_without_orders(monkeypatch, n):
    fake_bench(monkeypatch, n=n)
    b = PaperSimBroker()
    trend_live.run(b, submit=True, now=WHEN)
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "QQQ history" in e["message"] for e in events())


def test_kill_state_is_on_disk_before_any_order_is_sent(monkeypatch):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions={"QQQ": 100.0})
    seen = []
    send = b.submit_market_on_close
    b.submit_market_on_close = (
        lambda o: seen.append(json.loads(trend_live.STATE_FILE.read_text())["kill"]["killed"]) or send(o))
    trend_live.run(b, submit=True, now=WHEN)
    assert seen == [True]


@pytest.mark.parametrize("submit", [False, True])
@pytest.mark.parametrize("held", [{"QQQ": 10.0}, {}])
def test_killed_run_only_ever_sells_what_it_holds(monkeypatch, submit, held):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions=held)
    trend_live.run(b, submit=submit, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == ([("QQQ", "sell")] if submit and held else [])


def test_stray_position_is_never_liquidated(monkeypatch):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions={"NVDA": 1.0})
    trend_live.run(b, submit=True, now=WHEN)
    assert b.submitted == [] and json.loads(trend_live.STATE_FILE.read_text())["kill"]["killed"] is False


def test_cutoff_does_not_record_a_submit_day(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker()
    b.can_submit_moc = lambda: (False, "past the cutoff")
    trend_live.run(b, submit=True, now=WHEN)
    assert json.loads(trend_live.STATE_FILE.read_text())["last_submit_day"] is None


@pytest.mark.parametrize("day, previous", [(15, None), (26, 25)])  # stale data / a session missing from the data
def test_old_data_never_trades(monkeypatch, day, previous):
    fake_bench(monkeypatch)  # last bar 2026-11-24
    b = PaperSimBroker()
    if previous:
        b.previous_session = lambda today: datetime(2026, 11, previous).date()
    trend_live.run(b, submit=True, now=datetime(2026, 12 if day == 15 else 11, day, 12, 0, tzinfo=live.ET))
    assert b.submitted == []


@pytest.mark.parametrize("rows, runs", [(199, False), (200, True)])
def test_benchmark_needs_the_full_trend_window(monkeypatch, rows, runs):
    fake_bench(monkeypatch, n=rows + 1)  # +1: today's bar is dropped
    b = PaperSimBroker()
    trend_live.run(b, submit=True, now=WHEN)
    assert bool(b.submitted) is runs


def disk_full(*args):
    raise OSError("disk full")


def test_kill_liquidates_even_if_the_state_cannot_be_saved(monkeypatch):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    monkeypatch.setattr(trend_live, "save_state", disk_full)
    b = PaperSimBroker(equity=60_000.0, positions={"QQQ": 100.0})
    with pytest.raises(OSError):
        trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "sell")]
    assert any(e["kind"] == "alert" and "could not save" in e["message"] for e in events())


def test_no_entry_if_the_state_cannot_be_saved(monkeypatch):
    fake_bench(monkeypatch)
    monkeypatch.setattr(trend_live, "save_state", disk_full)
    b = PaperSimBroker()
    with pytest.raises(OSError):
        trend_live.run(b, submit=True, now=WHEN)
    assert b.submitted == []


def test_interrupted_save_keeps_the_previous_state(monkeypatch):
    trend_live.save_state({"kill": "old"})
    monkeypatch.setattr("os.replace", disk_full)
    with pytest.raises(OSError):
        trend_live.save_state({"kill": "new"})
    assert trend_live.load_state() == {"kill": "old"}


def unwritable_logs(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    monkeypatch.setattr(trend_live, "LOG_DIR", blocker / "logs")


def test_no_entry_if_saving_fails_after_a_dry_run(monkeypatch):
    fake_bench(monkeypatch)
    b = PaperSimBroker()
    trend_live.run(b, submit=False, now=WHEN)
    monkeypatch.setattr(trend_live, "save_state", disk_full)
    with pytest.raises(OSError):
        trend_live.run(b, submit=True, now=WHEN)
    assert b.submitted == []


def test_kill_liquidates_on_a_completely_full_disk(monkeypatch, tmp_path):
    fake_bench(monkeypatch)
    trend_live.STATE_FILE.write_text(json.dumps(KILLED))
    monkeypatch.setattr(trend_live, "save_state", disk_full)
    unwritable_logs(monkeypatch, tmp_path)
    b = PaperSimBroker(equity=60_000.0, positions={"QQQ": 100.0})
    with pytest.raises(OSError):
        trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "sell")]


def test_no_entry_without_a_writable_log(monkeypatch, tmp_path):
    fake_bench(monkeypatch)
    unwritable_logs(monkeypatch, tmp_path)
    b = PaperSimBroker()
    with pytest.raises(OSError):
        trend_live.run(b, submit=True, now=WHEN)
    assert b.submitted == []


def test_order_event_is_retried_until_it_is_written(monkeypatch, tmp_path):
    fake_bench(monkeypatch)
    good = trend_live.LOG_DIR
    b = PaperSimBroker()
    b.orders_since = lambda since: [{"client_order_id": "tm-x", "status": "filled", "filled_qty": 1}]
    unwritable_logs(monkeypatch, tmp_path)
    trend_live.run(b, submit=False, now=WHEN)
    monkeypatch.setattr(trend_live, "LOG_DIR", good)
    trend_live.run(b, submit=False, now=WHEN)
    trend_live.run(b, submit=False, now=WHEN)
    assert sum(e["kind"] == "fill" for e in events()) == 1


# ---------- wrong-account guard ----------

OWN, OTHER = "PA-TEST-TREND", "PA-TEST-MOMENTUM"
KILLED_STATE = json.dumps({"last_submit_day": None, "last_kill_check": None, "logged_orders": [],
                           "kill": {"peak": 100_000.0, "killed": True, "days_killed": 1}})


def accounts(monkeypatch, own=OWN, other=OTHER):
    for name, value in (("ALPACA_TREND_ACCOUNT_NUMBER", own), ("ALPACA_ACCOUNT_NUMBER", other)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.mark.parametrize("own, other, actual", [(None, OTHER, OWN), (OWN, OTHER, OTHER), (OWN, OWN, OWN)],
                         ids=["unset", "other account", "same twice"])
@pytest.mark.parametrize("saved", [KILLED_STATE, None], ids=["killed", "no state"])
@pytest.mark.parametrize("submit", [True, False], ids=["submit", "dry run"])
def test_wrong_account_is_refused_before_state_or_orders(monkeypatch, own, other, actual, saved, submit):
    fake_bench(monkeypatch)
    monkeypatch.setattr(live, "LOG_DIR", trend_live.LOG_DIR.parent / "momentum_logs")
    accounts(monkeypatch, own, other)
    if saved:
        trend_live.STATE_FILE.write_text(saved)
    # all cash or holding only QQQ: nothing but the account number tells the accounts apart
    for positions in ({}, {"QQQ": 10.0}):
        b = PaperSimBroker(positions=positions, account=actual)
        with pytest.raises(SystemExit) as exc:
            trend_live.run(b, submit=submit, now=WHEN)
        assert exc.value.code == 1 and b.submitted == []
    assert (trend_live.STATE_FILE.read_text() if trend_live.STATE_FILE.exists() else None) == saved
    assert any(e["kind"] == "alert" and "ALPACA_TREND_ACCOUNT_NUMBER" in e["message"] for e in events())


def test_right_account_still_liquidates_when_market_data_is_down(monkeypatch):
    accounts(monkeypatch)
    monkeypatch.setattr(trend_live, "load_prices", down)
    trend_live.STATE_FILE.write_text(KILLED_STATE)
    b = PaperSimBroker(positions={"QQQ": 10.0}, account=OWN)
    with pytest.raises(ConnectionError):
        trend_live.run(b, submit=True, now=WHEN)
    assert [(o.symbol, o.side) for o in b.submitted] == [("QQQ", "sell")]


@pytest.mark.parametrize("actual, allowed", [(OWN, True), (OTHER, False)])
def test_reset_kill_switch_checks_the_account(monkeypatch, actual, allowed):
    accounts(monkeypatch)
    monkeypatch.delenv("ALPACA_TREND_API_KEY", raising=False)
    monkeypatch.setattr(live, "LOG_DIR", trend_live.LOG_DIR.parent / "momentum_logs")
    trend_live.STATE_FILE.write_text(KILLED_STATE)
    monkeypatch.setattr(trend_live, "AlpacaPaperBroker",
                        lambda key, secret: PaperSimBroker(equity=70_000.0, account=actual))
    monkeypatch.setattr("sys.argv", ["trend_live.py", "--reset-kill-switch"])
    if allowed:
        trend_live.main()
        assert json.loads(trend_live.STATE_FILE.read_text())["kill"]["killed"] is False
    else:
        with pytest.raises(SystemExit):
            trend_live.main()
        assert trend_live.STATE_FILE.read_text() == KILLED_STATE
    assert events()
    assert not (trend_live.LOG_DIR.parent / "momentum_logs").exists()  # trend alerts go to the trend log
