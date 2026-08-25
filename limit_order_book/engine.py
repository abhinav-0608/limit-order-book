"""Order-entry facade: validation -> matching -> book update.

Split out from matching.py because "what happens to an unfilled remainder"
is order-type-specific policy (limit orders rest, market orders don't),
not part of the matching walk itself.

Design decision, not covered explicitly in the design doc's modify/replace
section: a PRICE-changing modify can itself become immediately marketable
-- e.g. you modify a resting bid's price upward until it's at or above the
current best ask. Real exchanges let this execute immediately rather than
just re-resting at the new price unmatched. Since a price change always
loses time priority anyway (see design doc section 1), the correct and
simplest implementation is: cancel the old resting order, then resubmit it
through the exact same path a brand new limit order would take (validate,
match, rest-or-fill). A pure quantity-INCREASE modify (price unchanged)
can never newly cross the book by itself -- a resting order's price
relationship to the opposite side can't change just by sitting there, only
by a new incoming order arriving -- but routing it through the same path
is harmless (the crossing check just says "no" immediately) and keeps the
logic in one place rather than two.

Design decision, unilateral, flagged for review: no self-trade prevention.
Order has no owner/trader-id field (the design doc listed this as an open
question rather than deciding it), so an incoming order CAN match against
a resting order that was, in reality, submitted by the same trader. Adding
prevention would require adding that field and a check in matching.py;
deliberately left out for now rather than silently guessed at.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .matching import match_incoming_order
from .order_book import DuplicateOrderId, OrderBook, UnknownOrderId
from .orders import Order, OrderStatus, OrderType
from .trade import Trade


class InvalidOrder(Exception):
    pass


def _validate_new_order(order: Order) -> None:
    if order.quantity <= 0:
        raise InvalidOrder(f"quantity must be positive, got {order.quantity}")
    if order.order_type is OrderType.LIMIT:
        if order.price is None or order.price <= 0:
            raise InvalidOrder(f"limit order must have a positive price, got {order.price}")
    else:
        if order.price is not None:
            raise InvalidOrder("market order must not specify a price")


def submit_limit_order(book: OrderBook, order: Order) -> List[Trade]:
    """Submit a new limit order: match whatever crosses immediately in
    price-time priority, then rest any unfilled remainder on the book.
    Raises InvalidOrder for a non-positive quantity/price, DuplicateOrderId
    if order_id is already live on the book."""
    _validate_new_order(order)
    if order.order_id in book:
        raise DuplicateOrderId(order.order_id)

    trades = match_incoming_order(book, order)
    if order.remaining_quantity == 0:
        order.status = OrderStatus.FILLED
    else:
        book.add_resting_order(order)
    return trades


def submit_market_order(book: OrderBook, order: Order) -> List[Trade]:
    """Submit a market order: match immediately against the best available
    prices, walking the book until filled or it runs out. Never rests --
    any unfilled remainder is dropped (order.status becomes CANCELLED), not
    stored, because a market order has no price to sit on the book at. A
    market order finding nothing to trade against is a valid, accepted
    outcome (zero trades), not a rejection."""
    _validate_new_order(order)
    if order.order_id in book:
        raise DuplicateOrderId(order.order_id)

    trades = match_incoming_order(book, order)
    order.status = OrderStatus.FILLED if order.remaining_quantity == 0 else OrderStatus.CANCELLED
    return trades


def modify_order(
    book: OrderBook,
    order_id,
    new_price: Optional[int] = None,
    new_quantity: Optional[int] = None,
) -> Tuple[Order, List[Trade]]:
    """Modify/replace a resting order. `new_price`/`new_quantity` are the
    new absolute values (not deltas); omit (None) to leave a field as-is.

    Priority rule (design doc section 1):
      - quantity decreased, price unchanged -> mutated in place, keeps its
        queue position.
      - quantity increased, or price changed at all -> loses priority:
        cancelled and resubmitted as a new order (new sequence number, back
        of the queue at the resulting price -- and, per the module
        docstring, possibly filled immediately if the new price crosses).

    Raises UnknownOrderId if order_id isn't currently resting on the book
    (this includes market orders, which by construction never rest -- there
    is nothing to modify once one has been submitted). Raises InvalidOrder
    if neither field is given, or either given value isn't positive.
    """
    order = book.get_order(order_id)
    if order is None:
        raise UnknownOrderId(order_id)
    if new_price is None and new_quantity is None:
        raise InvalidOrder("modify must change price and/or quantity")
    if new_quantity is not None and new_quantity <= 0:
        raise InvalidOrder(f"quantity must be positive, got {new_quantity}")
    if new_price is not None and new_price <= 0:
        raise InvalidOrder(f"price must be positive, got {new_price}")

    target_price = new_price if new_price is not None else order.price
    target_quantity = new_quantity if new_quantity is not None else order.remaining_quantity
    loses_priority = (target_price != order.price) or (target_quantity > order.remaining_quantity)

    if not loses_priority:
        level = book.get_level(order.side, order.price)
        level.change_remaining_quantity(order, target_quantity)
        return order, []

    book.cancel_order(order_id)
    order.price = target_price
    order.quantity = target_quantity
    order.remaining_quantity = target_quantity
    order.status = OrderStatus.OPEN
    trades = submit_limit_order(book, order)
    return order, trades
