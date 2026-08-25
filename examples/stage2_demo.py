"""Stage 2 demo: limit-order matching with price-time priority.

Walks through the exact scenario from the design doc, section 4:
a book gets swept across two price levels by one aggressive order, with a
remainder left resting. Run: python examples/stage2_demo.py
"""

from limit_order_book import Order, OrderBook, Side, submit_limit_order


def print_book(book: OrderBook) -> None:
    print(f"  best bid: {book.best_bid()}   best ask: {book.best_ask()}")
    print("  bids (best first):", book.depth(Side.BUY))
    print("  asks (best first):", book.depth(Side.SELL))


def main() -> None:
    book = OrderBook()
    for o in [
        Order.new_limit("A", Side.BUY, 1000, 100),
        Order.new_limit("B", Side.BUY, 1000, 50),
        Order.new_limit("C", Side.BUY, 999, 200),
        Order.new_limit("D1", Side.SELL, 1005, 50),
        Order.new_limit("D2", Side.SELL, 1005, 30),
        Order.new_limit("E", Side.SELL, 1006, 150),
    ]:
        submit_limit_order(book, o)

    print("Starting book:")
    print_book(book)

    print("\nSubmitting aggressive BUY limit H: price=1006, qty=300 ...")
    trades = submit_limit_order(book, Order.new_limit("H", Side.BUY, 1006, 300))

    print("\nTrades generated (in order):")
    for t in trades:
        print(f"  {t.quantity} @ {t.price}   maker={t.maker_order_id}  taker={t.taker_order_id}")

    print("\nBook after matching:")
    print_book(book)
    print("\nIs the book crossed?", book.is_crossed())


if __name__ == "__main__":
    main()
