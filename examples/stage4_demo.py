"""Stage 4 demo: feed a text order-entry file through the engine and print
trades plus final book state.

Run: python examples/stage4_demo.py
(Equivalently: python -m limit_order_book.io_adapter examples/sample_orders.txt)
"""

from pathlib import Path

from limit_order_book import OrderBook, run_stream

SAMPLE_FILE = Path(__file__).parent / "sample_orders.txt"


def main() -> None:
    book = OrderBook()
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        run_stream(book, f)


if __name__ == "__main__":
    main()
