"""Stage 6: throughput benchmark.

Times how fast the engine processes a synthetic order-flow stream, and
reports where the time went broken down by action type -- a single
aggregate events/sec number doesn't tell you much on its own; see design
doc section 5 for why matching cost scales with orders actually touched,
not book size, so LIMIT/MARKET (which can walk several price levels) are
expected to cost more per event than CANCEL/MODIFY (near-constant work).

Caveat worth being upfront about: wrapping every single event in its own
time.perf_counter() call adds measurement overhead of its own (a
perf_counter() call is not free), so the per-action breakdown here is a
rough signal, not a precise profile. For an actual profile, run this
under cProfile (`python -m cProfile -s cumulative benchmarks/bench_throughput.py`)
instead of trusting the per-action numbers to the microsecond.

Run: PYTHONPATH=. python benchmarks/bench_throughput.py [--events N] [--seed S]
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict

from generate_flow import FlowConfig, generate_order_flow

from limit_order_book import (
    DuplicateOrderId,
    InvalidOrder,
    OrderBook,
    UnknownOrderId,
    apply_command,
)


def run_benchmark(num_events: int, seed: int) -> None:
    config = FlowConfig(num_events=num_events, seed=seed)
    print(f"Generating {num_events:,} synthetic events (seed={seed})...")
    events = generate_order_flow(config)

    book = OrderBook()
    accepted = defaultdict(int)
    rejected = defaultdict(int)
    time_by_action = defaultdict(float)

    start = time.perf_counter()
    for event in events:
        action = event["action"]
        t0 = time.perf_counter()
        try:
            apply_command(book, event)
            accepted[action] += 1
        except (InvalidOrder, DuplicateOrderId, UnknownOrderId):
            rejected[action] += 1
        time_by_action[action] += time.perf_counter() - t0
    elapsed = time.perf_counter() - start

    print(
        f"\nProcessed {num_events:,} events in {elapsed:.3f}s "
        f"-> {num_events / elapsed:,.0f} events/sec"
    )

    print("\nAccepted vs rejected, by action:")
    for action in ("LIMIT", "MARKET", "CANCEL", "MODIFY"):
        print(f"  {action:8s} accepted={accepted[action]:7d}  rejected={rejected[action]:6d}")

    print("\nWall-clock time by action type (rough breakdown, see caveat above):")
    for action, t in sorted(time_by_action.items(), key=lambda kv: -kv[1]):
        n = accepted[action] + rejected[action]
        avg_us = (t / n * 1e6) if n else 0.0
        print(f"  {action:8s} total={t:7.3f}s  avg={avg_us:7.2f}us/event  n={n}")

    print(
        f"\nFinal book: {len(book):,} live resting orders, "
        f"best_bid={book.best_bid()}, best_ask={book.best_ask()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the matching engine's throughput.")
    parser.add_argument("--events", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_benchmark(args.events, args.seed)


if __name__ == "__main__":
    main()
