import pytest

from limit_order_book import DuplicateOrderId, Order, Side, UnknownOrderId


def limit(order_id, side, price, qty):
    return Order.new_limit(order_id, side, price=price, quantity=qty)


# -- best bid / ask & ordering ------------------------------------------------

def test_best_bid_is_highest_price(book):
    book.add_resting_order(limit("a", Side.BUY, 100, 10))
    book.add_resting_order(limit("b", Side.BUY, 105, 10))
    book.add_resting_order(limit("c", Side.BUY, 99, 10))
    assert book.best_bid() == 105


def test_best_ask_is_lowest_price(book):
    book.add_resting_order(limit("a", Side.SELL, 110, 10))
    book.add_resting_order(limit("b", Side.SELL, 105, 10))
    book.add_resting_order(limit("c", Side.SELL, 115, 10))
    assert book.best_ask() == 105


def test_best_bid_ask_none_when_side_empty(book):
    assert book.best_bid() is None
    assert book.best_ask() is None


def test_depth_bids_sorted_highest_first(book):
    book.add_resting_order(limit("a", Side.BUY, 100, 10))
    book.add_resting_order(limit("b", Side.BUY, 105, 5))
    book.add_resting_order(limit("c", Side.BUY, 99, 20))
    prices = [p for p, _, _ in book.depth(Side.BUY)]
    assert prices == [105, 100, 99]


def test_depth_asks_sorted_lowest_first(book):
    book.add_resting_order(limit("a", Side.SELL, 110, 10))
    book.add_resting_order(limit("b", Side.SELL, 105, 5))
    book.add_resting_order(limit("c", Side.SELL, 120, 20))
    prices = [p for p, _, _ in book.depth(Side.SELL)]
    assert prices == [105, 110, 120]


# -- FIFO within a price level ------------------------------------------------

def test_fifo_preserved_within_price_level(book):
    a = limit("a", Side.BUY, 100, 10)
    b = limit("b", Side.BUY, 100, 20)
    c = limit("c", Side.BUY, 100, 30)
    book.add_resting_order(a)
    book.add_resting_order(b)
    book.add_resting_order(c)
    level = book.get_level(Side.BUY, 100)
    assert [o.order_id for o in level] == ["a", "b", "c"]


def test_sequence_numbers_strictly_increasing(book):
    ids = ["a", "b", "c"]
    for oid in ids:
        book.add_resting_order(limit(oid, Side.BUY, 100, 10))
    sequences = [book.get_order(oid).sequence for oid in ids]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


# -- cancel --------------------------------------------------------------

def test_cancel_removes_only_target_order(book):
    a = limit("a", Side.BUY, 100, 10)
    b = limit("b", Side.BUY, 100, 20)
    book.add_resting_order(a)
    book.add_resting_order(b)

    book.cancel_order("a")

    level = book.get_level(Side.BUY, 100)
    assert [o.order_id for o in level] == ["b"]
    assert book.get_order("a") is None
    assert "a" not in book


def test_cancel_last_order_at_price_removes_the_level(book):
    book.add_resting_order(limit("a", Side.BUY, 100, 10))
    book.cancel_order("a")
    assert book.get_level(Side.BUY, 100) is None
    assert book.best_bid() is None


def test_cancel_unknown_order_id_raises(book):
    with pytest.raises(UnknownOrderId):
        book.cancel_order("does-not-exist")


def test_cancelled_order_marked_and_cannot_be_cancelled_twice(book):
    from limit_order_book import OrderStatus

    book.add_resting_order(limit("a", Side.BUY, 100, 10))
    cancelled = book.cancel_order("a")
    assert cancelled.status == OrderStatus.CANCELLED
    with pytest.raises(UnknownOrderId):
        book.cancel_order("a")


# -- structural integrity -------------------------------------------------

def test_duplicate_order_id_rejected(book):
    book.add_resting_order(limit("a", Side.BUY, 100, 10))
    with pytest.raises(DuplicateOrderId):
        book.add_resting_order(limit("a", Side.SELL, 200, 5))
    # original order must be untouched
    original = book.get_order("a")
    assert original.side == Side.BUY and original.price == 100


def test_len_reflects_live_order_count(book):
    book.add_resting_order(limit("a", Side.BUY, 100, 10))
    book.add_resting_order(limit("b", Side.SELL, 200, 10))
    assert len(book) == 2
    book.cancel_order("a")
    assert len(book) == 1


def test_order_id_index_and_price_level_stay_consistent(book):
    for oid, price in [("a", 100), ("b", 100), ("c", 101)]:
        book.add_resting_order(limit(oid, Side.BUY, price, 10))
    book.cancel_order("b")

    # every id in the index is reachable from its price level...
    for oid in ("a", "c"):
        order = book.get_order(oid)
        level = book.get_level(Side.BUY, order.price)
        assert order in list(level)

    # ...and the cancelled id is gone from both places
    assert book.get_order("b") is None
    all_ids = {o.order_id for price, _, _ in book.depth(Side.BUY)
               for o in book.get_level(Side.BUY, price)}
    assert "b" not in all_ids
