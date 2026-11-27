"""The real Alpaca adapter against a fake client: no network, no keys."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from alpaca.common.enums import BaseURL
from alpaca.trading.enums import OrderSide, OrderStatus, QueryOrderStatus, TimeInForce

from broker import AlpacaPaperBroker, OrderRequest


class FakeClient:
    def __init__(self, minutes_left=60.0, is_open=True, url=BaseURL.TRADING_PAPER):
        self.minutes_left, self.is_open, self._base_url, self.sent = minutes_left, is_open, url, []

    def get_account(self):
        return NS(last_equity="101000.5", equity="90000")

    def get_clock(self):
        now = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
        return NS(is_open=self.is_open, timestamp=now, next_close=now + timedelta(minutes=self.minutes_left),
                  next_open=now)

    def get_all_positions(self):
        return [NS(symbol="NVDA", qty="7")]

    def get_orders(self, request):
        self.query = request
        return [NS(id=2, client_order_id="tm-y", symbol="NVDA", side=OrderSide.BUY, qty="7", status=OrderStatus.FILLED,
                   filled_qty="7", filled_avg_price="101.5")]

    def get_calendar(self, request):
        return [NS(date=date(2026, 11, 27)), NS(date=date(2026, 11, 30)), NS(date=date(2026, 12, 1))]

    def submit_order(self, req):
        self.sent.append(req)
        return NS(id=1, client_order_id=req.client_order_id, symbol=req.symbol, side=req.side, qty=req.qty,
                  status="accepted", filled_qty=0, filled_avg_price=None)


def adapter(monkeypatch, client):
    made = {}
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setattr("alpaca.trading.client.TradingClient",
                        lambda key, secret, paper: made.update(paper=paper) or client)
    broker = AlpacaPaperBroker()
    assert made == {"paper": True}
    return broker


@pytest.mark.parametrize("side, expected", [("buy", OrderSide.BUY), ("sell", OrderSide.SELL)])
def test_sends_a_market_on_close_order(monkeypatch, side, expected):
    client = FakeClient()
    out = adapter(monkeypatch, client).submit_market_on_close(OrderRequest("NVDA", 7, side, "tm-x"))
    req = client.sent[0]
    assert (req.symbol, req.qty, req.side, req.time_in_force, req.client_order_id) == (
        "NVDA", 7, expected, TimeInForce.CLS, "tm-x")
    assert out["status"] == "accepted"


@pytest.mark.parametrize("minutes, is_open, ok", [(60, True, True), (15, True, True), (14.9, True, False),
                                                  (60, False, False)])
def test_cutoff(monkeypatch, minutes, is_open, ok):
    assert adapter(monkeypatch, FakeClient(minutes, is_open)).can_submit_moc()[0] is ok


def test_uses_previous_close_equity_and_previous_session(monkeypatch):
    b = adapter(monkeypatch, FakeClient())
    assert b.last_close_equity() == 101000.5
    assert b.previous_session(date(2026, 12, 1)) == date(2026, 11, 30)


def test_refuses_a_non_paper_endpoint(monkeypatch):
    with pytest.raises(RuntimeError, match="paper endpoint"):
        adapter(monkeypatch, FakeClient(url=BaseURL.TRADING_LIVE))


def test_reads_positions_and_all_orders(monkeypatch):
    client = FakeClient()
    b = adapter(monkeypatch, client)
    assert b.positions() == {"NVDA": 7.0}
    (order,) = b.orders_since("2026-11-24")
    assert order["client_order_id"] == "tm-y"
    assert (order["status"], order["side"], order["filled_qty"], order["filled_avg_price"]) == (
        "filled", "buy", 7.0, 101.5)
    assert client.query.status == QueryOrderStatus.ALL and client.query.after == datetime(2026, 11, 24)
