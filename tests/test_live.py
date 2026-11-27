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
    monkeypatch.setattr(live, "unpriced_members", lambda days: [])
    monkeypatch.setattr(live, "unpriced_symbols", lambda symbols, day: [])
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


def test_unpriced_member_aborts_without_orders(monkeypatch):
    fake_market(monkeypatch)
    monkeypatch.setattr(live, "unpriced_members", lambda days: ["A"])
    b = PaperSimBroker(positions={"A": 10.0})
    live.run(b, submit=True, now=datetime(2026, 11, 24, 12, 0, tzinfo=live.ET))
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "no price" in e["message"] for e in events(live.LOG_DIR))
    assert json.loads(live.STATE_FILE.read_text())["last_rebalance_month"] is None  # a re-run can still rebalance


def test_unpriced_target_aborts_without_orders(monkeypatch):
    fake_market(monkeypatch)
    # every target lacks a real price on the last bar, e.g. it left the index after the signal day
    monkeypatch.setattr(live, "unpriced_symbols", lambda symbols, day: sorted(symbols))
    b = PaperSimBroker()
    live.run(b, submit=True, now=datetime(2026, 11, 24, 12, 0, tzinfo=live.ET))
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "for target" in e["message"] for e in events(live.LOG_DIR))
    assert json.loads(live.STATE_FILE.read_text())["last_rebalance_month"] is None


def test_no_prior_month_data_aborts_without_orders(monkeypatch):
    fake_market(monkeypatch)
    monkeypatch.setattr(live, "previous_month_end", lambda index, today: None)
    b = PaperSimBroker(positions={"A": 10.0})
    live.run(b, submit=True, now=datetime(2026, 11, 24, 12, 0, tzinfo=live.ET))
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "before this month" in e["message"] for e in events(live.LOG_DIR))
    assert not any(e["kind"] == "error" for e in events(live.LOG_DIR))


def test_missing_previous_session_aborts(monkeypatch):
    fake_market(monkeypatch)  # last bar 2026-11-24
    b = PaperSimBroker()
    b.previous_session = lambda today: datetime(2026, 11, 25).date()
    live.run(b, submit=True, now=datetime(2026, 11, 26, 12, 0, tzinfo=live.ET))
    assert b.submitted == []
    assert any(e["kind"] == "alert" and "previous session" in e["message"] for e in events(live.LOG_DIR))


# ---------- failure handling ----------

KILLED = {"last_rebalance_month": None, "last_kill_check": None, "logged_orders": [],
          "kill": {"peak": 100_000.0, "killed": False, "days_killed": 0}}
NOON = datetime(2026, 11, 24, 12, 0, tzinfo=live.ET)


def alerts():
    return [e["message"] for e in events(live.LOG_DIR) if e["kind"] == "alert"]


def down(*args, **kwargs):
    raise ConnectionError("down")


@pytest.mark.parametrize("failing", ["prices", "order history"])
def test_kill_switch_liquidates_even_when_a_data_source_is_down(monkeypatch, failing):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions={"A": 10.0})
    if failing == "prices":
        monkeypatch.setattr(live, "load_universe", down)
    else:
        b.orders_since = down
    with pytest.raises(ConnectionError):
        live.run(b, submit=True, now=NOON)
    assert [(o.symbol, o.side) for o in b.submitted] == [("A", "sell")]
    assert json.loads(live.STATE_FILE.read_text())["kill"]["killed"] is True


@pytest.mark.parametrize("positions", [{"A": 10.0}, {}])
def test_active_kill_switch_alerts_on_every_run(monkeypatch, positions):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions=positions)
    live.run(b, submit=False, now=NOON)
    live.run(b, submit=False, now=NOON)  # same day, e.g. the --submit run after the dry run
    assert sum("KILL SWITCH" in m for m in alerts()) == 2


@pytest.mark.parametrize("cut", [slice(-60, None), slice(None, -2)])  # too short / ends a day before the stocks (today's bar is dropped)
def test_unusable_benchmark_aborts_without_orders(monkeypatch, cut):
    fake_market(monkeypatch)
    bench = live.load_prices(["QQQ"], refresh=True).iloc[cut]
    monkeypatch.setattr(live, "load_prices", lambda tickers, refresh: bench)
    b = PaperSimBroker()
    live.run(b, submit=True, now=NOON)
    assert b.submitted == [] and any("QQQ history" in m for m in alerts())
    assert not any(e["kind"] == "error" for e in events(live.LOG_DIR))


def test_account_holding_qqq_is_left_alone(monkeypatch):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions={"QQQ": 10.0})
    live.run(b, submit=True, now=NOON)
    assert b.submitted == [] and any("wrong account" in m for m in alerts())
    assert json.loads(live.STATE_FILE.read_text())["kill"]["killed"] is False  # its equity is not ours either


@pytest.mark.parametrize("submit", [False, True])
def test_every_order_is_printed_before_anything_is_sent(monkeypatch, capsys, submit):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    live.run(b, submit=submit, now=NOON)
    out = capsys.readouterr().out
    planned = [e for e in events(live.LOG_DIR) if e["kind"] == "planned_order"]
    assert len(planned) == 3 and all(f"symbol={e['symbol']}" in out and f"qty={e['qty']}" in out for e in planned)
    if submit:
        assert out.rindex("[planned_order]") < out.index("[order_submitted]")


def test_cutoff_is_checked_before_each_order(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    b.can_submit_moc = lambda: (not b.submitted, "past the closing-auction cutoff")
    live.run(b, submit=True, now=NOON)
    assert len(b.submitted) == 1
    assert any("not submitting" in m and "1 of 3" in m for m in alerts())
    assert json.loads(live.STATE_FILE.read_text())["last_rebalance_month"] is None


def test_kill_state_is_on_disk_before_any_order_is_sent(monkeypatch):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions={"A": 10.0})
    seen = []
    send = b.submit_market_on_close
    b.submit_market_on_close = lambda o: seen.append(json.loads(live.STATE_FILE.read_text())["kill"]["killed"]) or send(o)
    live.run(b, submit=True, now=NOON)
    assert seen == [True]  # a closed terminal or power cut later in the run cannot forget the kill


def test_clock_error_mid_batch_stops_and_says_how_far_it_got(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    calls = []

    def clock():
        calls.append(1)
        return down() if len(calls) == 2 else (True, "")

    b.can_submit_moc = clock
    live.run(b, submit=True, now=NOON)
    assert len(b.submitted) == 1
    assert any("not submitting" in m and "1 of 3" in m for m in alerts())
    assert [e["where"] for e in events(live.LOG_DIR) if e["kind"] == "error"] == ["cutoff_check"]
    assert json.loads(live.STATE_FILE.read_text())["last_rebalance_month"] is None


@pytest.mark.parametrize("submit", [False, True])
@pytest.mark.parametrize("held", [{"A": 10.0}, {}])
def test_killed_run_only_ever_sells_what_it_holds(monkeypatch, submit, held):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    b = PaperSimBroker(equity=60_000.0, positions=held)
    live.run(b, submit=submit, now=NOON)
    assert [(o.symbol, o.side) for o in b.submitted] == ([("A", "sell")] if submit and held else [])
    assert not any(e["kind"] == "signal" for e in events(live.LOG_DIR))


def test_rejected_order_leaves_the_month_open(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    send, tried = b.submit_market_on_close, []

    def flaky(o):
        tried.append(o)
        if len(tried) == 1:
            raise RuntimeError("rejected")
        return send(o)

    b.submit_market_on_close = flaky
    live.run(b, submit=True, now=NOON)
    assert len(b.submitted) == 2  # the rest still go
    assert json.loads(live.STATE_FILE.read_text())["last_rebalance_month"] is None
    assert any("order failed" in m for m in alerts())


@pytest.mark.parametrize("status", ["rejected", "canceled", "expired"])
def test_unfilled_order_alerts_once(monkeypatch, status):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    b.orders_since = lambda since: [{"client_order_id": "tm-x", "status": status, "filled_qty": 0}]
    live.run(b, submit=False, now=NOON)
    live.run(b, submit=False, now=NOON)
    assert sum(e["kind"] == "order_final" for e in events(live.LOG_DIR)) == 1
    assert sum(f"ended {status}" in m for m in alerts()) == 1


@pytest.mark.parametrize("rows, runs", [(199, False), (200, True)])
def test_benchmark_needs_the_full_trend_window_at_the_signal_day(monkeypatch, rows, runs):
    fake_market(monkeypatch)
    full = live.load_prices(["QQQ"], refresh=True)
    through_signal = len(full.loc[:"2026-10-30"])  # the month-end signal day for a November run
    bench = full.iloc[through_signal - rows:]
    monkeypatch.setattr(live, "load_prices", lambda tickers, refresh: bench)
    b = PaperSimBroker()
    live.run(b, submit=True, now=NOON)
    assert bool(b.submitted) is runs
    assert any("QQQ history" in m for m in alerts()) is not runs


def test_stocks_behind_the_benchmark_abort(monkeypatch):
    close = fake_market(monkeypatch)
    eligible = pd.DataFrame(True, index=close.index, columns=close.columns)
    monkeypatch.setattr(live, "load_universe", lambda kind, refresh: (close.iloc[:-2], eligible.iloc[:-2]))
    b = PaperSimBroker()
    live.run(b, submit=True, now=NOON)
    assert b.submitted == [] and any("QQQ history" in m for m in alerts())


def disk_full(state):
    raise OSError("disk full")


def test_kill_liquidates_even_if_the_state_cannot_be_saved(monkeypatch):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    monkeypatch.setattr(live, "save_state", disk_full)
    b = PaperSimBroker(equity=60_000.0, positions={"A": 10.0})
    with pytest.raises(OSError):  # still loud: the final save fails too
        live.run(b, submit=True, now=NOON)
    assert [(o.symbol, o.side) for o in b.submitted] == [("A", "sell")]
    assert any("could not save" in m for m in alerts())


def test_no_rebalance_if_the_state_cannot_be_saved(monkeypatch):
    fake_market(monkeypatch)
    monkeypatch.setattr(live, "save_state", disk_full)
    b = PaperSimBroker()
    with pytest.raises(OSError):
        live.run(b, submit=True, now=NOON)
    assert b.submitted == []  # an unrecorded month would be traded again


def test_interrupted_save_keeps_the_previous_state(monkeypatch):
    live.save_state({"kill": "old"})
    monkeypatch.setattr("os.replace", disk_full_replace)
    with pytest.raises(OSError):
        live.save_state({"kill": "new"})
    assert live.load_state() == {"kill": "old"}


def disk_full_replace(src, dst):
    raise OSError("interrupted")


def unwritable_logs(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    monkeypatch.setattr(live, "LOG_DIR", blocker / "logs")


def test_no_rebalance_if_saving_fails_after_a_dry_run(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    live.run(b, submit=False, now=NOON)
    monkeypatch.setattr(live, "save_state", disk_full)
    with pytest.raises(OSError):
        live.run(b, submit=True, now=NOON)
    assert b.submitted == []


def test_kill_liquidates_on_a_completely_full_disk(monkeypatch, tmp_path, capsys):
    fake_market(monkeypatch)
    live.STATE_FILE.write_text(json.dumps(KILLED))
    monkeypatch.setattr(live, "save_state", disk_full)
    unwritable_logs(monkeypatch, tmp_path)
    b = PaperSimBroker(equity=60_000.0, positions={"A": 10.0})
    with pytest.raises(OSError):
        live.run(b, submit=True, now=NOON)
    assert [(o.symbol, o.side) for o in b.submitted] == [("A", "sell")]
    assert "could not write the log" in capsys.readouterr().err


def test_no_rebalance_without_a_writable_log(monkeypatch, tmp_path):
    fake_market(monkeypatch)
    unwritable_logs(monkeypatch, tmp_path)
    b = PaperSimBroker()
    with pytest.raises(OSError):
        live.run(b, submit=True, now=NOON)
    assert b.submitted == []


def test_benchmark_missing_the_signal_day_aborts(monkeypatch):
    fake_market(monkeypatch)
    bench = live.load_prices(["QQQ"], refresh=True).drop(pd.Timestamp("2026-10-30"))
    monkeypatch.setattr(live, "load_prices", lambda tickers, refresh: bench)
    b = PaperSimBroker()
    live.run(b, submit=True, now=NOON)
    assert b.submitted == [] and any("signal day" in m for m in alerts())


@pytest.mark.parametrize("status, kind", [("filled", "fill"), ("rejected", "order_final")])
def test_order_event_is_retried_until_it_is_written(monkeypatch, tmp_path, status, kind):
    fake_market(monkeypatch)
    good = live.LOG_DIR
    b = PaperSimBroker()
    b.orders_since = lambda since: [{"client_order_id": "tm-x", "status": status, "filled_qty": 1}]
    unwritable_logs(monkeypatch, tmp_path)
    live.run(b, submit=False, now=NOON)
    assert json.loads(live.STATE_FILE.read_text())["logged_orders"] == []
    monkeypatch.setattr(live, "LOG_DIR", good)
    live.run(b, submit=False, now=NOON)
    live.run(b, submit=False, now=NOON)
    assert sum(e["kind"] == kind for e in events(good)) == 1


def test_order_is_retried_if_only_its_alert_was_not_written(monkeypatch):
    fake_market(monkeypatch)
    b = PaperSimBroker()
    b.orders_since = lambda since: [{"client_order_id": "tm-x", "status": "rejected", "filled_qty": 0}]
    write = live.log_event
    monkeypatch.setattr(live, "log_event", lambda kind, **data: False if kind == "alert" else write(kind, **data))
    live.run(b, submit=False, now=NOON)
    assert json.loads(live.STATE_FILE.read_text())["logged_orders"] == []
    monkeypatch.setattr(live, "log_event", write)
    live.run(b, submit=False, now=NOON)
    assert sum("ended rejected" in m for m in alerts()) == 1
    assert json.loads(live.STATE_FILE.read_text())["logged_orders"] == ["tm-x"]
