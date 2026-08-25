from limit_order_book import Order, Side
from limit_order_book.price_level import PriceLevel


def make(order_id, qty):
    return Order.new_limit(order_id, Side.BUY, price=100, quantity=qty)


def test_append_preserves_fifo_order():
    level = PriceLevel(100)
    a, b, c = make("a", 10), make("b", 20), make("c", 30)
    level.append(a)
    level.append(b)
    level.append(c)
    assert list(level) == [a, b, c]
    assert level.peek_front() is a
    assert len(level) == 3
    assert level.total_quantity == 60


def test_remove_from_front_middle_and_back():
    level = PriceLevel(100)
    a, b, c = make("a", 10), make("b", 20), make("c", 30)
    for o in (a, b, c):
        level.append(o)

    level.remove(b)  # middle
    assert list(level) == [a, c]
    assert level.total_quantity == 40

    level.remove(a)  # now-front
    assert list(level) == [c]
    assert level.peek_front() is c

    level.remove(c)  # last remaining
    assert list(level) == []
    assert level.is_empty()
    assert level.total_quantity == 0


def test_removed_order_pointers_are_cleared():
    level = PriceLevel(100)
    a, b = make("a", 10), make("b", 20)
    level.append(a)
    level.append(b)
    level.remove(a)
    assert a._prev is None and a._next is None


def test_change_remaining_quantity_updates_total():
    level = PriceLevel(100)
    a = make("a", 10)
    level.append(a)
    level.change_remaining_quantity(a, 4)
    assert a.remaining_quantity == 4
    assert level.total_quantity == 4


def test_reappend_after_remove_goes_to_back():
    # Used by modify/replace (Stage 3) when an order loses priority: it is
    # removed and re-appended, which must land it at the tail, not restored
    # to its old middle position.
    level = PriceLevel(100)
    a, b, c = make("a", 10), make("b", 20), make("c", 30)
    for o in (a, b, c):
        level.append(o)
    level.remove(a)
    level.append(a)
    assert list(level) == [b, c, a]
