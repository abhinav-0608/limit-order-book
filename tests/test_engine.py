import pytest

from limit_order_book import (
    DuplicateOrderId,
    InvalidOrder,
    Order,
    OrderStatus,
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


def seed_book(book):
    for o in [
        limit("A", Side.BUY, 1000, 100),
        limit("B", Side.BUY, 999, 200),
        limit("D", Side.SELL, 1005, 80),
        limit("E", Side.SELL, 1006, 150),
    ]:
        submit_limit_order(book, o)
    return book


# -- market orders ---------------------------------------------------------

def test_market_order_fully_fills_from_best_price(book):
    seed_book(book)
    trades = submit_market_order(book, market("M", Side.BUY, 40))
    assert len(trades) == 1
    assert trades[0].price == 1005
    assert trades[0].quantity == 40
    m = book.get_order("M")
    assert m is None  # never rests, and it's not resting since fully filled


def test_market_order_never_rests_when_book_runs_out(book):
    seed_book(book)
    # total ask liquidity is 80 + 150 = 230; ask for more than that
    order = market("M", Side.BUY, 500)
    trades = submit_market_order(book, order)
    filled = sum(t.quantity for t in trades)
    assert filled == 230
    assert order.remaining_quantity == 500 - 230
    assert order.status == OrderStatus.CANCELLED  # remainder dropped
    assert "M" not in book  # never touched the book's resting index
    assert book.best_ask() is None


def test_market_order_against_empty_side_is_accepted_with_zero_trades(book):
    # no rejection -- a market order finding nothing to match is valid
    order = market("M", Side.BUY, 10)
    trades = submit_market_order(book, order)
    assert trades == []
    assert order.status == OrderStatus.CANCELLED


def test_market_order_sweeps_multiple_price_levels(book):
    seed_book(book)
    trades = submit_market_order(book, market("M", Side.BUY, 150))
    assert [(t.maker_order_id, t.quantity) for t in trades] == [("D", 80), ("E", 70)]


# -- modify/replace: quantity decrease keeps priority ----------------------

def test_modify_quantity_decrease_keeps_queue_position(book):
    a = limit("a", Side.BUY, 1000, 100)
    b = limit("b", Side.BUY, 1000, 50)
    submit_limit_order(book, a)
    submit_limit_order(book, b)
    original_sequence = a.sequence

    modified, trades = modify_order(book, "a", new_quantity=20)

    assert trades == []
    assert modified.sequence == original_sequence  # priority preserved
    assert modified.remaining_quantity == 20
    level = book.get_level(Side.BUY, 1000)
    assert [o.order_id for o in level] == ["a", "b"]  # still at the front


# -- modify/replace: quantity increase loses priority -----------------------

def test_modify_quantity_increase_moves_to_back_of_queue(book):
    a = limit("a", Side.BUY, 1000, 50)
    b = limit("b", Side.BUY, 1000, 50)
    submit_limit_order(book, a)
    submit_limit_order(book, b)
    old_sequence = a.sequence

    modified, trades = modify_order(book, "a", new_quantity=200)

    assert trades == []
    assert modified.sequence != old_sequence
    assert modified.sequence > b.sequence
    level = book.get_level(Side.BUY, 1000)
    assert [o.order_id for o in level] == ["b", "a"]  # a is now behind b
    assert modified.remaining_quantity == 200


# -- modify/replace: price change loses priority -----------------------

def test_modify_price_change_moves_to_new_level_back_of_queue(book):
    seed_book(book)
    a = book.get_order("A")
    old_sequence = a.sequence

    modified, trades = modify_order(book, "A", new_price=998)

    assert trades == []
    assert modified.price == 998
    assert modified.sequence != old_sequence
    assert book.get_level(Side.BUY, 1000) is None  # A was alone at 1000
    new_level = book.get_level(Side.BUY, 998)
    assert [o.order_id for o in new_level] == ["A"]


def test_modify_price_change_that_crosses_book_trades_immediately():
    from limit_order_book import OrderBook

    book = OrderBook()
    submit_limit_order(book, limit("bid", Side.BUY, 990, 50))
    submit_limit_order(book, limit("ask", Side.SELL, 1000, 30))

    # push the resting bid's price up until it crosses the ask
    modified, trades = modify_order(book, "bid", new_price=1000)

    assert len(trades) == 1
    assert trades[0].price == 1000  # maker (the pre-existing ask) price
    assert trades[0].maker_order_id == "ask"
    assert trades[0].taker_order_id == "bid"
    assert modified.remaining_quantity == 20  # 50 - 30
    assert modified.status == OrderStatus.OPEN
    assert book.best_ask() is None
    assert book.get_level(Side.BUY, 1000).peek_front() is modified


# -- rejections --------------------------------------------------------

def test_submit_rejects_non_positive_quantity(book):
    with pytest.raises(InvalidOrder):
        submit_limit_order(book, limit("bad", Side.BUY, 1000, 0))
    with pytest.raises(InvalidOrder):
        submit_limit_order(book, limit("bad2", Side.BUY, 1000, -5))
    assert "bad" not in book and "bad2" not in book


def test_submit_rejects_non_positive_price(book):
    with pytest.raises(InvalidOrder):
        submit_limit_order(book, limit("bad", Side.BUY, 0, 10))
    with pytest.raises(InvalidOrder):
        submit_limit_order(book, limit("bad2", Side.BUY, -5, 10))


def test_submit_rejects_duplicate_order_id_even_if_it_would_fully_fill(book):
    seed_book(book)
    # "D" is already resting; submitting a NEW aggressive order under the
    # same id must be rejected outright, even though it would fully match
    # and therefore never touch add_resting_order's own duplicate check.
    with pytest.raises(DuplicateOrderId):
        submit_limit_order(book, limit("D", Side.BUY, 1005, 10))


def test_cancel_unknown_order_id_rejected(book):
    with pytest.raises(UnknownOrderId):
        book.cancel_order("nope")


def test_modify_unknown_order_id_rejected(book):
    with pytest.raises(UnknownOrderId):
        modify_order(book, "nope", new_quantity=10)


def test_modify_market_order_id_rejected_because_it_never_rests(book):
    seed_book(book)
    order = market("M", Side.BUY, 10)
    submit_market_order(book, order)
    with pytest.raises(UnknownOrderId):
        modify_order(book, "M", new_quantity=5)


def test_modify_rejects_zero_or_negative_quantity(book):
    submit_limit_order(book, limit("a", Side.BUY, 1000, 50))
    with pytest.raises(InvalidOrder):
        modify_order(book, "a", new_quantity=0)
    with pytest.raises(InvalidOrder):
        modify_order(book, "a", new_quantity=-10)


def test_modify_rejects_non_positive_price(book):
    submit_limit_order(book, limit("a", Side.BUY, 1000, 50))
    with pytest.raises(InvalidOrder):
        modify_order(book, "a", new_price=0)


def test_modify_rejects_no_op_call(book):
    submit_limit_order(book, limit("a", Side.BUY, 1000, 50))
    with pytest.raises(InvalidOrder):
        modify_order(book, "a")


def test_market_order_rejects_non_positive_quantity(book):
    with pytest.raises(InvalidOrder):
        submit_market_order(book, market("bad", Side.BUY, 0))
