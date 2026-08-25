"""Price-time priority matching: the walk that turns a crossing incoming
order into trades against resting orders.

This module owns the *matching policy* only -- which resting orders trade,
in what order, and at what price. It deliberately does NOT decide what
happens to an incoming order's unfilled remainder (rest it? drop it?) --
that differs by order type (limit vs market) and belongs to the caller
(engine.py), which is what keeps this walk itself reusable for both.
"""

from __future__ import annotations

from typing import List

from .order_book import OrderBook
from .orders import Order, OrderType, Side
from .trade import Trade


def _opposite_side(side: Side) -> Side:
    return Side.SELL if side is Side.BUY else Side.BUY


def _crosses(incoming: Order, resting_price: int) -> bool:
    """Would `incoming` accept a trade at `resting_price`?"""
    if incoming.order_type is OrderType.MARKET:
        return True
    if incoming.side is Side.BUY:
        return incoming.price >= resting_price
    return incoming.price <= resting_price


def match_incoming_order(book: OrderBook, incoming: Order) -> List[Trade]:
    """Match `incoming` against the opposite side of `book` in strict
    price-time priority: best price first, FIFO within a price. Stops when
    `incoming` is fully filled, the book no longer crosses, or the opposite
    side runs out. Mutates `book` and `incoming` (remaining_quantity) in
    place and returns the trades generated, oldest first.
    """
    opposite = _opposite_side(incoming.side)
    trades: List[Trade] = []

    while incoming.remaining_quantity > 0:
        best_price = book.best_ask() if opposite is Side.SELL else book.best_bid()
        if best_price is None or not _crosses(incoming, best_price):
            break

        level = book.get_level(opposite, best_price)
        while incoming.remaining_quantity > 0 and not level.is_empty():
            resting = level.peek_front()
            traded_qty = min(incoming.remaining_quantity, resting.remaining_quantity)

            level.change_remaining_quantity(
                resting, resting.remaining_quantity - traded_qty
            )
            incoming.remaining_quantity -= traded_qty

            trades.append(
                Trade(
                    sequence=book.next_trade_sequence(),
                    price=best_price,
                    quantity=traded_qty,
                    maker_order_id=resting.order_id,
                    taker_order_id=incoming.order_id,
                    maker_side=opposite,
                )
            )

            if resting.is_filled:
                book.remove_filled_order(resting)
            # else: partial fill on the resting side -- it stays exactly
            # where it is, at the front of this level, per FIFO.

    return trades
