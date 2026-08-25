"""Text order-entry format + driver.

Parses one action per line, feeds each to the engine, and reports what
happened. Kept separate from engine.py so the engine has zero knowledge
that any text format exists -- it only ever sees Order objects.

Line format (comma-separated; blank lines and lines starting with '#' are
ignored; whitespace around fields is stripped):

    LIMIT,<order_id>,<BUY|SELL>,<price>,<quantity>
    MARKET,<order_id>,<BUY|SELL>,<quantity>
    CANCEL,<order_id>
    MODIFY,<order_id>,<new_price or blank>,<new_quantity or blank>

Design decision: the design doc offered "text, CSV, or JSON" as options.
This implements one plain-text/CSV-style format rather than all three,
since building three parsers for one learning project is scope the task
doesn't need. A JSON-lines format would only require replacing
parse_line(); apply_command() and everything downstream is format-agnostic
already, since it only ever sees a plain dict.
"""

from __future__ import annotations

import sys
from typing import Iterable, List, Optional, TextIO

from .engine import InvalidOrder, modify_order, submit_limit_order, submit_market_order
from .order_book import DuplicateOrderId, OrderBook, UnknownOrderId
from .orders import Order, Side
from .trade import Trade


class ParseError(Exception):
    pass


def parse_line(line: str) -> Optional[dict]:
    """Parse one line into a command dict, or None for a blank/comment
    line. Raises ParseError for anything malformed."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    parts = [p.strip() for p in stripped.split(",")]
    action = parts[0].upper()

    try:
        if action == "LIMIT":
            _, order_id, side, price, quantity = parts
            return {
                "action": "LIMIT",
                "order_id": order_id,
                "side": Side[side.upper()],
                "price": int(price),
                "quantity": int(quantity),
            }
        if action == "MARKET":
            _, order_id, side, quantity = parts
            return {
                "action": "MARKET",
                "order_id": order_id,
                "side": Side[side.upper()],
                "quantity": int(quantity),
            }
        if action == "CANCEL":
            _, order_id = parts
            return {"action": "CANCEL", "order_id": order_id}
        if action == "MODIFY":
            _, order_id, new_price, new_quantity = parts
            return {
                "action": "MODIFY",
                "order_id": order_id,
                "new_price": int(new_price) if new_price else None,
                "new_quantity": int(new_quantity) if new_quantity else None,
            }
    except (ValueError, KeyError) as e:
        raise ParseError(f"malformed {action!r} line {line!r}: {e}") from e

    raise ParseError(f"unknown action {action!r} in line {line!r}")


def apply_command(book: OrderBook, cmd: dict) -> List[Trade]:
    """Apply one parsed command to `book`. Raises InvalidOrder,
    DuplicateOrderId, or UnknownOrderId on rejection -- the caller decides
    whether that's fatal (see run_stream, which reports and continues)."""
    action = cmd["action"]
    if action == "LIMIT":
        order = Order.new_limit(cmd["order_id"], cmd["side"], cmd["price"], cmd["quantity"])
        return submit_limit_order(book, order)
    if action == "MARKET":
        order = Order.new_market(cmd["order_id"], cmd["side"], cmd["quantity"])
        return submit_market_order(book, order)
    if action == "CANCEL":
        book.cancel_order(cmd["order_id"])
        return []
    if action == "MODIFY":
        _, trades = modify_order(book, cmd["order_id"], cmd["new_price"], cmd["new_quantity"])
        return trades
    raise AssertionError(f"unreachable: unknown action {action!r}")  # parse_line already validated


def format_trade(trade: Trade) -> str:
    return (
        f"TRADE {trade.quantity}@{trade.price} "
        f"maker={trade.maker_order_id} taker={trade.taker_order_id}"
    )


def format_book(book: OrderBook) -> str:
    lines = [f"best_bid={book.best_bid()} best_ask={book.best_ask()}"]
    lines.append("bids: " + ", ".join(f"{p}x{q}({n})" for p, q, n in book.depth(Side.BUY)))
    lines.append("asks: " + ", ".join(f"{p}x{q}({n})" for p, q, n in book.depth(Side.SELL)))
    return "\n".join(lines)


def run_stream(book: OrderBook, lines: Iterable[str], out: TextIO = sys.stdout) -> None:
    """Feed a stream of order-entry lines into `book`, printing each trade
    as it happens and a rejection message (rather than crashing) for any
    line that fails to parse or is rejected by the engine."""
    for raw_line in lines:
        try:
            cmd = parse_line(raw_line)
        except ParseError as e:
            print(f"REJECTED: {e}", file=out)
            continue
        if cmd is None:
            continue

        try:
            trades = apply_command(book, cmd)
        except (InvalidOrder, DuplicateOrderId, UnknownOrderId) as e:
            print(f"REJECTED: {cmd} -- {type(e).__name__}: {e}", file=out)
            continue

        print(f"OK {cmd['action']} {cmd['order_id']}", file=out)
        for trade in trades:
            print(format_trade(trade), file=out)

    print("\n-- final book state --", file=out)
    print(format_book(book), file=out)


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Feed order-entry commands into a fresh order book.")
    parser.add_argument("file", nargs="?", help="path to an order-entry file; defaults to stdin")
    args = parser.parse_args(argv)

    book = OrderBook()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            run_stream(book, f)
    else:
        run_stream(book, sys.stdin)


if __name__ == "__main__":
    main()
