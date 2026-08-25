"""Order model: the data the rest of the book/matching code operates on.

Prices are integer ticks, not floats -- see the design doc, section 2, for why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Union

OrderId = Union[int, str]


class Side(Enum):
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    LIMIT = auto()
    MARKET = auto()


class OrderStatus(Enum):
    OPEN = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()


@dataclass(slots=True)
class Order:
    """A single order.

    ``_prev`` / ``_next`` implement an intrusive doubly linked list: while an
    order is resting in a PriceLevel, those two fields ARE its node in that
    level's FIFO queue. This avoids allocating a separate wrapper node per
    order and is what makes O(1) cancel-by-id possible (see PriceLevel).
    They are only meaningful while the order is resting; do not read them
    from outside price_level.py.
    """

    order_id: OrderId
    side: Side
    order_type: OrderType
    quantity: int
    remaining_quantity: int
    price: Optional[int] = None
    sequence: Optional[int] = None
    status: OrderStatus = OrderStatus.OPEN

    _prev: Optional["Order"] = field(default=None, repr=False, compare=False)
    _next: Optional["Order"] = field(default=None, repr=False, compare=False)

    @classmethod
    def new_limit(cls, order_id: OrderId, side: Side, price: int, quantity: int) -> "Order":
        return cls(
            order_id=order_id,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            remaining_quantity=quantity,
            price=price,
        )

    @classmethod
    def new_market(cls, order_id: OrderId, side: Side, quantity: int) -> "Order":
        return cls(
            order_id=order_id,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            remaining_quantity=quantity,
            price=None,
        )

    @property
    def is_filled(self) -> bool:
        return self.remaining_quantity == 0
