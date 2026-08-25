"""Stage 5: the design doc's section 8 invariant checklist, plus a seeded
randomized simulation that re-checks every invariant after every single
operation. The scenario-specific tests in the earlier test_*.py files
already cover most of these individually; this module (a) adds the few
behavioral invariants nothing else exercises yet, and (b) adds integration
coverage that no single hand-written scenario can give -- many operations
interacting, in an order nobody specifically designed a test around.

Note on approach: a "real" property-based test would use a library like
hypothesis (stateful testing / RuleBasedStateMachine is the standard tool
for this). Deliberately not adding that dependency here -- a seeded
`random.Random` simulation gets most of the same value (many interacting
operations, invariants re-checked throughout) with zero new dependencies
and a test that's trivially readable by anyone who knows stdlib `random`.
Worth reconsidering if this project grows past a learning/CV scope.
"""

import random

import pytest

from limit_order_book import (
    DuplicateOrderId,
    InvalidOrder,
    Order,
    OrderBook,
    Side,
    UnknownOrderId,
    modify_order,
    submit_limit_order,
    submit_market_order,
)


def limit(order_id, side, price, qty):
    return Order.new_limit(order_id, side, price=price, quantity=qty)


def market(order_id, side, qty):
    return Order.new_market(order_id, side, quantity=qty)


# -- reusable invariant checks, one per bullet in the design doc's checklist --

def assert_bids_sorted_highest_first(book):
    prices = [p for p, _, _ in book.depth(Side.BUY)]
    assert prices == sorted(prices, reverse=True)


def assert_asks_sorted_lowest_first(book):
    prices = [p for p, _, _ in book.depth(Side.SELL)]
    assert prices == sorted(prices)


def assert_fifo_within_every_level(book):
    for side in (Side.BUY, Side.SELL):
        for price, _, _ in book.depth(side):
            sequences = [o.sequence for o in book.get_level(side, price)]
            assert sequences == sorted(sequences)


def assert_not_crossed(book):
    assert not book.is_crossed()


def assert_quantity_bounds_and_level_totals_consistent(book):
    for side in (Side.BUY, Side.SELL):
        for price, total_qty, _ in book.depth(side):
            level = book.get_level(side, price)
            summed = 0
            for o in level:
                assert 0 < o.remaining_quantity <= o.quantity
                summed += o.remaining_quantity
            assert summed == total_qty


def assert_order_id_index_consistent(book):
    for side in (Side.BUY, Side.SELL):
        for price, _, _ in book.depth(side):
            for o in book.get_level(side, price):
                assert book.get_order(o.order_id) is o


def assert_all_invariants(book):
    assert_bids_sorted_highest_first(book)
    assert_asks_sorted_lowest_first(book)
    assert_fifo_within_every_level(book)
    assert_not_crossed(book)
    assert_quantity_bounds_and_level_totals_consistent(book)
    assert_order_id_index_consistent(book)


# -- behavioral invariants not already covered elsewhere --------------------

def test_filled_order_cannot_be_cancelled(book):
    submit_limit_order(book, limit("resting", Side.SELL, 100, 10))
    submit_limit_order(book, limit("taker", Side.BUY, 100, 10))  # fully fills resting
    assert book.get_order("resting") is None
    with pytest.raises(UnknownOrderId):
        book.cancel_order("resting")


def test_filled_order_cannot_be_modified(book):
    submit_limit_order(book, limit("resting", Side.SELL, 100, 10))
    submit_limit_order(book, limit("taker", Side.BUY, 100, 10))
    with pytest.raises(UnknownOrderId):
        modify_order(book, "resting", new_quantity=5)


def test_cancelled_order_cannot_later_trade(book):
    submit_limit_order(book, limit("resting", Side.SELL, 100, 10))
    book.cancel_order("resting")

    trades = submit_limit_order(book, limit("taker", Side.BUY, 100, 10))
    assert trades == []  # nothing left to trade against
    assert book.get_order("taker").remaining_quantity == 10  # rests untouched


def test_invariants_hold_on_a_freshly_constructed_empty_book(book):
    assert_all_invariants(book)  # trivial, but a real base case worth pinning


# -- randomized simulation ---------------------------------------------

def test_randomized_simulation_maintains_all_invariants():
    rng = random.Random(12345)  # fixed seed: deterministic, reproducible failures
    book = OrderBook()
    live_ids: list = []
    next_id = 0

    for _ in range(500):
        action = rng.choice(["limit", "limit", "limit", "market", "cancel", "modify"])
        try:
            if action == "limit":
                oid = f"o{next_id}"
                next_id += 1
                side = rng.choice([Side.BUY, Side.SELL])
                price = rng.randint(95, 105)
                qty = rng.randint(1, 50)
                submit_limit_order(book, limit(oid, side, price, qty))
                if oid in book:
                    live_ids.append(oid)

            elif action == "market":
                oid = f"o{next_id}"
                next_id += 1
                side = rng.choice([Side.BUY, Side.SELL])
                qty = rng.randint(1, 50)
                submit_market_order(book, market(oid, side, qty))
                # market orders never rest -- nothing to track in live_ids

            elif action == "cancel" and live_ids:
                oid = rng.choice(live_ids)
                if oid in book:
                    book.cancel_order(oid)

            elif action == "modify" and live_ids:
                oid = rng.choice(live_ids)
                if oid in book:
                    new_price = rng.randint(95, 105) if rng.random() < 0.5 else None
                    new_qty = rng.randint(1, 50) if rng.random() < 0.5 else None
                    if new_price is not None or new_qty is not None:
                        modify_order(book, oid, new_price, new_qty)
        except (InvalidOrder, DuplicateOrderId, UnknownOrderId):
            pass  # rejections are expected background noise, not failures

        live_ids = [i for i in live_ids if i in book]  # drop filled/cancelled ids
        assert_all_invariants(book)
