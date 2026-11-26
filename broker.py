"""Broker layer. PAPER TRADING ONLY.

There is deliberately no way to construct a live client from this module: `paper=True` is
hard-coded and the account endpoint is checked. Keys come from environment variables
ALPACA_API_KEY / ALPACA_SECRET_KEY and are never logged or printed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

PAPER_URL_FRAGMENT = "paper-api.alpaca.markets"


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    qty: int                 # whole shares, > 0
    side: str                # "buy" | "sell"
    client_order_id: str     # deterministic, so a re-run on the same day cannot double-submit


class Broker(Protocol):
    def last_close_equity(self) -> float: ...
    def positions(self) -> dict[str, float]: ...
    def submit_market_on_close(self, order: OrderRequest) -> dict: ...
    def orders_since(self, iso_date: str) -> list[dict]: ...
    def can_submit_moc(self) -> tuple[bool, str]: ...
    def previous_session(self, today: date) -> date | None: ...


class AlpacaPaperBroker:
    """Thin wrapper over alpaca-py's TradingClient, locked to the paper environment."""

    def __init__(self, key_env: str = "ALPACA_API_KEY", secret_env: str = "ALPACA_SECRET_KEY") -> None:
        """`key_env`/`secret_env` name the environment variables to read, so a second strategy can use a
        second paper account (the account holds the positions and equity, so strategies cannot share one)."""
        from alpaca.trading.client import TradingClient

        key, secret = os.environ.get(key_env), os.environ.get(secret_env)
        if not key or not secret:
            raise RuntimeError(f"set {key_env} and {secret_env} (paper account keys)")
        self._client = TradingClient(key, secret, paper=True)  # never change: paper only
        url = getattr(self._client, "_base_url", "")
        base = str(getattr(url, "value", url))
        if PAPER_URL_FRAGMENT not in base:
            raise RuntimeError(f"refusing to trade: client is not pointed at the paper endpoint ({base!r})")

    def last_close_equity(self) -> float:
        # Account equity as of the previous close: the same quantity the backtest kill switch uses.
        return float(self._client.get_account().last_equity)

    def positions(self) -> dict[str, float]:
        return {p.symbol: float(p.qty) for p in self._client.get_all_positions()}

    def submit_market_on_close(self, order: OrderRequest) -> dict:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(
            symbol=order.symbol,
            qty=order.qty,
            side=OrderSide.BUY if order.side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.CLS,  # fill at the closing auction, like the backtest
            client_order_id=order.client_order_id,
        )
        return _order_dict(self._client.submit_order(req))

    def can_submit_moc(self) -> tuple[bool, str]:
        """Market-on-close orders must arrive while the market is open, before the ~15:50 ET cutoff."""
        clock = self._client.get_clock()
        if not clock.is_open:
            return False, f"market closed; next open {clock.next_open}"
        minutes_left = (clock.next_close - clock.timestamp).total_seconds() / 60
        if minutes_left < 15:
            return False, f"only {minutes_left:.0f} min to close: past the closing-auction cutoff"
        return True, f"{minutes_left:.0f} min to close"

    def previous_session(self, today: date) -> date | None:
        """Last trading day before `today` on the exchange calendar."""
        from alpaca.trading.requests import GetCalendarRequest

        days = self._client.get_calendar(GetCalendarRequest(start=today - timedelta(days=14), end=today))
        return max((d.date for d in days if d.date < today), default=None)

    def orders_since(self, iso_date: str) -> list[dict]:
        from datetime import datetime

        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=datetime.fromisoformat(iso_date), limit=500)
        return [_order_dict(o) for o in self._client.get_orders(req)]


def _order_dict(o) -> dict:
    return {
        "id": str(o.id),
        "client_order_id": o.client_order_id,
        "symbol": o.symbol,
        "side": str(getattr(o.side, "value", o.side)),
        "qty": float(o.qty or 0),
        "status": str(getattr(o.status, "value", o.status)),
        "filled_qty": float(o.filled_qty or 0),
        "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
    }


class PaperSimBroker:
    """Offline stand-in for dry runs and tests: holds positions in memory, fills nothing."""

    def __init__(self, equity: float = 100_000.0, positions: dict[str, float] | None = None) -> None:
        self._equity, self._positions, self.submitted = equity, dict(positions or {}), []

    def last_close_equity(self) -> float:
        return self._equity

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def submit_market_on_close(self, order: OrderRequest) -> dict:
        self.submitted.append(order)
        return {"client_order_id": order.client_order_id, "symbol": order.symbol, "side": order.side,
                "qty": order.qty, "status": "simulated"}

    def orders_since(self, iso_date: str) -> list[dict]:
        return []

    def can_submit_moc(self) -> tuple[bool, str]:
        return True, "offline simulation"

    def previous_session(self, today: date) -> date | None:
        return None  # no exchange calendar offline
