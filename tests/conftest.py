import pytest

from limit_order_book import OrderBook


@pytest.fixture
def book() -> OrderBook:
    return OrderBook()
