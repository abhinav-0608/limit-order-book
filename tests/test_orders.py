from limit_order_book import Order, OrderType, Side


def test_new_limit_sets_remaining_equal_to_quantity():
    o = Order.new_limit("A", Side.BUY, price=100, quantity=10)
    assert o.quantity == 10
    assert o.remaining_quantity == 10
    assert o.order_type == OrderType.LIMIT
    assert o.price == 100
    assert o.sequence is None  # only assigned once accepted by the book


def test_new_market_has_no_price():
    o = Order.new_market("B", Side.SELL, quantity=5)
    assert o.order_type == OrderType.MARKET
    assert o.price is None
    assert o.remaining_quantity == 5


def test_is_filled_property():
    o = Order.new_limit("C", Side.BUY, price=100, quantity=10)
    assert not o.is_filled
    o.remaining_quantity = 0
    assert o.is_filled
