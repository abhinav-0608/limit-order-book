"""Stage 3 demo: market orders, modify/replace, and rejections.

Run: python examples/stage3_demo.py
"""

from limit_order_book import (
    InvalidOrder,
    Order,
    OrderBook,
    Side,
    modify_order,
    submit_limit_order,
    submit_market_order,
)


def print_book(book: OrderBook) -> None:
    print(f"  best bid: {book.best_bid()}   best ask: {book.best_ask()}")
    print("  bids (best first):", book.depth(Side.BUY))
    print("  asks (best first):", book.depth(Side.SELL))


def main() -> None:
    book = OrderBook()
    for o in [
        Order.new_limit("bid1", Side.BUY, 990, 50),
        Order.new_limit("bid2", Side.BUY, 989, 100),
        Order.new_limit("ask1", Side.SELL, 1000, 30),
        Order.new_limit("ask2", Side.SELL, 1001, 200),
    ]:
        submit_limit_order(book, o)

    print("Starting book:")
    print_book(book)

    print("\nMarket BUY for 60 (sweeps ask1 fully, part of ask2)...")
    trades = submit_market_order(book, Order.new_market("mkt1", Side.BUY, 60))
    for t in trades:
        print(f"  {t.quantity} @ {t.price}  maker={t.maker_order_id}")
    print_book(book)

    print("\nModify bid2: shrink quantity 100 -> 40 (keeps its queue slot)...")
    modified, trades = modify_order(book, "bid2", new_quantity=40)
    print(f"  sequence still {modified.sequence}, remaining={modified.remaining_quantity}")

    print("\nModify bid1: push price 990 -> 1001 (crosses the book, trades immediately)...")
    modified, trades = modify_order(book, "bid1", new_price=1001)
    for t in trades:
        print(f"  {t.quantity} @ {t.price}  maker={t.maker_order_id}  taker={t.taker_order_id}")
    print_book(book)

    print("\nAttempting an invalid submission (zero quantity)...")
    try:
        submit_limit_order(book, Order.new_limit("bad", Side.BUY, 900, 0))
    except InvalidOrder as e:
        print(f"  rejected as expected: {e}")


if __name__ == "__main__":
    main()
