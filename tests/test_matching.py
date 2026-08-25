"""Regression tests for the exact worked examples in the design doc,
section 4, plus the cross-cutting invariants matching must always satisfy."""

from limit_order_book import Order, Side, submit_limit_order


def limit(order_id, side, price, qty):
    return Order.new_limit(order_id, side, price=price, quantity=qty)


def seed_book(book):
    """The book used throughout section 4's examples."""
    for o in [
        limit("A", Side.BUY, 1000, 100),
        limit("B", Side.BUY, 1000, 50),
        limit("C", Side.BUY, 999, 200),
        limit("D1", Side.SELL, 1005, 50),
        limit("D2", Side.SELL, 1005, 30),
        limit("E", Side.SELL, 1006, 150),
    ]:
        submit_limit_order(book, o)
    return book


# -- Example 1: resting order that does not cross -----------------------

def test_non_crossing_limit_order_just_rests(book):
    seed_book(book)
    trades = submit_limit_order(book, limit("F", Side.BUY, 998, 50))
    assert trades == []
    assert book.get_order("F").remaining_quantity == 50
    assert book.best_bid() == 1000  # unchanged, F is worse than existing bids
    assert [p for p, _, _ in book.depth(Side.BUY)] == [1000, 999, 998]


# -- Example 2: aggressive limit order, partial fill on the resting side --

def test_crossing_order_partially_fills_resting_order(book):
    seed_book(book)
    trades = submit_limit_order(book, limit("G", Side.BUY, 1005, 30))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.price == 1005  # resting (maker) price, not the taker's
    assert trade.quantity == 30
    assert trade.maker_order_id == "D1"
    assert trade.taker_order_id == "G"

    assert book.get_order("G") is None  # fully filled, never rested
    d1 = book.get_order("D1")
    assert d1.remaining_quantity == 20  # 50 - 30
    level = book.get_level(Side.SELL, 1005)
    assert level.peek_front() is d1  # still at the front: partial fill keeps priority
    assert [o.order_id for o in level] == ["D1", "D2"]


# -- Example 3: consumes multiple orders at one price, then another level,
#    then rests the remainder -------------------------------------------

def test_incoming_order_sweeps_one_price_then_another_then_rests(book):
    seed_book(book)
    trades = submit_limit_order(book, limit("H", Side.BUY, 1006, 300))

    assert [(t.maker_order_id, t.price, t.quantity) for t in trades] == [
        ("D1", 1005, 50),
        ("D2", 1005, 30),
        ("E", 1006, 150),
    ]

    # both ask levels fully consumed and removed
    assert book.get_level(Side.SELL, 1005) is None
    assert book.get_level(Side.SELL, 1006) is None
    assert book.best_ask() is None

    # remainder (300 - 50 - 30 - 150 = 70) rests as a new bid at 1006
    h = book.get_order("H")
    assert h is not None
    assert h.remaining_quantity == 70
    assert h.price == 1006
    assert book.best_bid() == 1006

    # crucially: the book is not crossed, even though a bid now sits where
    # an ask used to be -- that ask level no longer exists
    assert not book.is_crossed()


# -- cross-cutting invariants ---------------------------------------------

def test_book_never_left_crossed_after_matching(book):
    seed_book(book)
    submit_limit_order(book, limit("X", Side.BUY, 1010, 40))
    assert not book.is_crossed()


def test_trade_quantities_conserve_against_maker_order(book):
    seed_book(book)
    trades = submit_limit_order(book, limit("H", Side.BUY, 1006, 300))
    filled_by_maker = {}
    for t in trades:
        filled_by_maker[t.maker_order_id] = filled_by_maker.get(t.maker_order_id, 0) + t.quantity
    assert filled_by_maker == {"D1": 50, "D2": 30, "E": 150}


def test_trades_always_price_at_the_maker_price(book):
    seed_book(book)
    # G's limit (1005) equals the maker's price here, so this alone doesn't
    # distinguish price improvement -- use a limit strictly above the ask.
    trades = submit_limit_order(book, limit("G", Side.BUY, 1050, 30))
    assert all(t.price == 1005 for t in trades)  # not 1050, the taker's limit


def test_fully_filled_incoming_order_never_rests(book):
    seed_book(book)
    submit_limit_order(book, limit("G", Side.BUY, 1005, 30))
    assert "G" not in book


def test_sell_side_matching_mirrors_buy_side(book):
    seed_book(book)
    # aggressive sell should hit the best bid (1000) first, FIFO: A then B
    trades = submit_limit_order(book, limit("Z", Side.SELL, 999, 120))
    assert [(t.maker_order_id, t.quantity) for t in trades] == [("A", 100), ("B", 20)]
    assert book.get_order("B").remaining_quantity == 30
