"""Stage 1 demo: order model + book skeleton, no matching.

Run: python examples/stage1_demo.py
"""

from limit_order_book import Order, OrderBook, Side


def print_book(book: OrderBook) -> None:
    print(f"  best bid: {book.best_bid()}   best ask: {book.best_ask()}")
    print("  bids (best first):", book.depth(Side.BUY))
    print("  asks (best first):", book.depth(Side.SELL))


def main() -> None:
    book = OrderBook()

    orders = [
        Order.new_limit("A", Side.BUY, price=1000, quantity=100),
        Order.new_limit("B", Side.BUY, price=1000, quantity=50),
        Order.new_limit("C", Side.BUY, price=999, quantity=200),
        Order.new_limit("D", Side.SELL, price=1005, quantity=80),
        Order.new_limit("E", Side.SELL, price=1006, quantity=150),
    ]
    for o in orders:
        book.add_resting_order(o)

    print("After inserting 5 resting orders:")
    print_book(book)

    print("\nCancelling order B (the second order at price 1000)...")
    book.cancel_order("B")
    print_book(book)

    print("\nFIFO order remaining at price 1000:",
          [o.order_id for o in book.get_level(Side.BUY, 1000)])


if __name__ == "__main__":
    main()
