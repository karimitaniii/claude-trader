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
