"""OrderBook: structural bookkeeping only (Stage 1) -- adding resting orders,
finding the best bid/ask, cancelling by id, and inspecting depth.

Deliberately contains NO matching/crossing logic. An order that would
technically "cross" the book if matching existed is still just inserted as
a resting order at this stage -- see design doc, Stage 1 scope. Matching is
added on top of this in matching.py (Stage 2).
"""

from __future__ import annotations

import itertools
from typing import Iterator, List, Optional, Tuple

from sortedcontainers import SortedDict

from .orders import Order, OrderId, OrderStatus, Side
from .price_level import PriceLevel


class DuplicateOrderId(Exception):
    pass


class UnknownOrderId(Exception):
    pass


class OrderBook:
    def __init__(self):
        # Both SortedDicts are kept ascending by price (their only mode).
        # "Best" therefore means opposite ends for the two sides:
        #   asks: best = lowest price  = index 0
        #   bids: best = highest price = index -1
        self._bids: "SortedDict[int, PriceLevel]" = SortedDict()
        self._asks: "SortedDict[int, PriceLevel]" = SortedDict()
        self._orders: dict[OrderId, Order] = {}
        self._sequence_counter = itertools.count(1)

    # -- internal helpers -----------------------------------------------

    def _levels(self, side: Side) -> "SortedDict[int, PriceLevel]":
        return self._bids if side is Side.BUY else self._asks

    def _next_sequence(self) -> int:
        return next(self._sequence_counter)

    def _remove_level_if_empty(self, side: Side, price: int) -> None:
        levels = self._levels(side)
        if levels[price].is_empty():
            del levels[price]

    # -- public API -------------------------------------------------------

    def best_bid(self) -> Optional[int]:
        return self._bids.peekitem(-1)[0] if self._bids else None

    def best_ask(self) -> Optional[int]:
        return self._asks.peekitem(0)[0] if self._asks else None

    def is_crossed(self) -> bool:
        bid, ask = self.best_bid(), self.best_ask()
        return bid is not None and ask is not None and bid >= ask

    def get_order(self, order_id: OrderId) -> Optional[Order]:
        return self._orders.get(order_id)

    def __contains__(self, order_id: OrderId) -> bool:
        return order_id in self._orders

    def get_level(self, side: Side, price: int) -> Optional[PriceLevel]:
        return self._levels(side).get(price)

    def add_resting_order(self, order: Order) -> None:
        """Insert `order` as a resting order. Assigns its sequence number.
        Does not attempt to match it against the opposite side -- see
        module docstring. Raises DuplicateOrderId if order.order_id is
        already on the book (an OrderBook-level structural invariant: the
        order_id index must never point at more than one live order)."""
        if order.order_id in self._orders:
            raise DuplicateOrderId(order.order_id)
        if order.price is None:
            raise ValueError("a resting order must have a price")

        order.sequence = self._next_sequence()
        levels = self._levels(order.side)
        level = levels.get(order.price)
        if level is None:
            level = PriceLevel(order.price)
            levels[order.price] = level
        level.append(order)
        self._orders[order.order_id] = order

    def cancel_order(self, order_id: OrderId) -> Order:
        """Remove a resting order from the book. Raises UnknownOrderId if
        it isn't on the book (already filled/cancelled, or never existed)."""
        order = self._orders.get(order_id)
        if order is None:
            raise UnknownOrderId(order_id)

        level = self._levels(order.side)[order.price]
        level.remove(order)
        self._remove_level_if_empty(order.side, order.price)
        order.status = OrderStatus.CANCELLED
        del self._orders[order_id]
        return order

    def depth(self, side: Side) -> List[Tuple[int, int, int]]:
        """Return [(price, total_quantity, order_count), ...] best price first."""
        levels = self._levels(side)
        prices: Iterator[int] = reversed(levels) if side is Side.BUY else iter(levels)
        return [(p, levels[p].total_quantity, len(levels[p])) for p in prices]

    def __len__(self) -> int:
        return len(self._orders)
