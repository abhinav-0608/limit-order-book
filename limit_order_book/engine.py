"""Order-entry facade: validation -> matching -> book update.

Split out from matching.py because "what happens to an unfilled remainder"
is order-type-specific policy (limit orders rest, market orders don't --
Stage 3), not part of the matching walk itself. Stage 2 only needs the
limit-order path; Stage 3 adds market orders, modify/replace, and
validation/rejection.
"""

from __future__ import annotations

from typing import List

from .matching import match_incoming_order
from .order_book import OrderBook
from .orders import Order
from .trade import Trade


def submit_limit_order(book: OrderBook, order: Order) -> List[Trade]:
    """Submit a new limit order: match whatever crosses immediately in
    price-time priority, then rest any unfilled remainder on the book."""
    trades = match_incoming_order(book, order)
    if order.remaining_quantity > 0:
        book.add_resting_order(order)
    return trades
