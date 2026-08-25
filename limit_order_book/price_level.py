"""FIFO queue of resting orders at a single price.

Implemented as a doubly linked list using the order objects themselves as
nodes (see Order._prev/_next), plus head/tail pointers here. This gives O(1)
append (new order arrives), O(1) pop-from-front (order at the front trades
or is removed), and O(1) removal of an arbitrary order -- PROVIDED the
caller already has a reference to that exact order object. Finding that
order by id is the job of OrderBook's order_id index, not this class.

A plain collections.deque would give the same O(1) append/pop-front, but
deque.remove(x) has to scan for x first (O(n)), so it can't give O(1)
cancel-by-id -- see design doc section 3 for the full argument.
"""

from __future__ import annotations

from typing import Iterator, Optional

from .orders import Order


class PriceLevel:
    def __init__(self, price: int):
        self.price = price
        self._head: Optional[Order] = None
        self._tail: Optional[Order] = None
        self._count = 0
        self.total_quantity = 0  # sum of remaining_quantity of all orders here

    def __len__(self) -> int:
        return self._count

    def is_empty(self) -> bool:
        return self._count == 0

    def peek_front(self) -> Optional[Order]:
        return self._head

    def append(self, order: Order) -> None:
        order._prev = self._tail
        order._next = None
        if self._tail is not None:
            self._tail._next = order
        else:
            self._head = order
        self._tail = order
        self._count += 1
        self.total_quantity += order.remaining_quantity

    def remove(self, order: Order) -> None:
        prev_order, next_order = order._prev, order._next
        if prev_order is not None:
            prev_order._next = next_order
        else:
            self._head = next_order
        if next_order is not None:
            next_order._prev = prev_order
        else:
            self._tail = prev_order
        order._prev = None
        order._next = None
        self._count -= 1
        self.total_quantity -= order.remaining_quantity

    def change_remaining_quantity(self, order: Order, new_remaining_quantity: int) -> None:
        """Update an order's remaining quantity in place (fill or shrink),
        keeping this level's cached total_quantity in sync. Does not touch
        queue position -- callers that need to move an order to the back
        must remove() and append() instead."""
        delta = new_remaining_quantity - order.remaining_quantity
        order.remaining_quantity = new_remaining_quantity
        self.total_quantity += delta

    def __iter__(self) -> Iterator[Order]:
        node = self._head
        while node is not None:
            yield node
            node = node._next
