from __future__ import annotations

from dataclasses import dataclass

from .orders import OrderId, Side


@dataclass(frozen=True, slots=True)
class Trade:
    """A single execution. `maker_side` is the side of the resting order --
    trades always print at the maker's (resting) price, never the taker's;
    see design doc section 4 for why."""

    sequence: int
    price: int
    quantity: int
    maker_order_id: OrderId
    taker_order_id: OrderId
    maker_side: Side
