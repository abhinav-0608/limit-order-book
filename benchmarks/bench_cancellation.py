"""Cancellation-scaling benchmark.

Question this answers: as the number of resting orders on the book grows,
does per-cancellation latency stay roughly flat? The architecture (see
design doc + order_book.py/price_level.py docstrings) is built for O(1)
cancel-by-id: a `dict[order_id] -> Order` gives direct lookup, and each
resting order is itself a node in its PriceLevel's doubly linked list, so
removing it needs no scan. This script only *measures* the existing
engine to see whether that expectation holds up in practice -- it does not
change or tune anything in limit_order_book/.

Order generation, and why it's guaranteed to rest rather than match: each
side draws its prices from a fixed band, and the two bands never overlap
and never touch (BUY from [9_500, 9_999], SELL from [10_001, 10_500]), so
best_bid is always < best_ask no matter what order the N orders arrive in
or how they cluster. That means every order can be submitted through the
real submit_limit_order() engine path (full validation + the matching
walk's crossing check) rather than bypassing it, while still being
provably certain to rest. Prices are drawn uniformly at random from each
500-tick band, which spreads orders across up to 500 distinct price
levels per side rather than piling everything onto one price.

Sample size: the task asks for >=1,000 cancellation samples "when the
book size permits" but also warns against cancelling such a large
fraction that the book changes shape mid-measurement. This script caps
the sample at 10% of the resting book (min(1_000, N // 10)), so N=1,000
gets 100 samples (permits less), and N=10,000/50,000/100,000 all get the
full 1,000. A separate, untimed warm-up removes a further small batch of
distinct orders first.

Run: PYTHONPATH=. python benchmarks/bench_cancellation.py [--seed S]
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import time
from dataclasses import dataclass
from typing import List

from limit_order_book import Order, OrderBook, Side, submit_limit_order

BUY_PRICE_LOW, BUY_PRICE_HIGH = 9_500, 9_999
SELL_PRICE_LOW, SELL_PRICE_HIGH = 10_001, 10_500
MAX_QUANTITY = 100
WARMUP_COUNT = 20


@dataclass
class CancellationResult:
    n_resting: int
    samples: int
    latencies_ns: List[int]

    @property
    def median_us(self) -> float:
        return statistics.median(self.latencies_ns) / 1_000

    @property
    def mean_us(self) -> float:
        return statistics.mean(self.latencies_ns) / 1_000

    @property
    def p95_us(self) -> float:
        return _percentile(sorted(self.latencies_ns), 0.95) / 1_000

    @property
    def total_time_us(self) -> float:
        return sum(self.latencies_ns) / 1_000


def _percentile(sorted_data: List[int], pct: float) -> float:
    """Linear-interpolation percentile (numpy's default method) over
    already-sorted data."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return float(sorted_data[0])
    k = (len(sorted_data) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(sorted_data[int(k)])
    return sorted_data[lo] * (hi - k) + sorted_data[hi] * (k - lo)


# -- book construction --------------------------------------------------

def build_resting_book(n: int, rng: random.Random) -> OrderBook:
    """Insert `n` valid resting LIMIT orders through the real engine path,
    split across two disjoint, non-overlapping price bands so nothing
    ever crosses (see module docstring). Returns the populated book;
    order ids are simply "o0".."o{n-1}", assigned in insertion order so
    the caller can retain them exactly for later sampling."""
    book = OrderBook()
    for i in range(n):
        side = Side.BUY if (i % 2 == 0) else Side.SELL
        if side is Side.BUY:
            price = rng.randint(BUY_PRICE_LOW, BUY_PRICE_HIGH)
        else:
            price = rng.randint(SELL_PRICE_LOW, SELL_PRICE_HIGH)
        quantity = rng.randint(1, MAX_QUANTITY)
        order = Order.new_limit(f"o{i}", side, price=price, quantity=quantity)
        trades = submit_limit_order(book, order)
        assert not trades, "resting-order setup must never match"
        assert order.order_id in book, "order must have rested, not filled"
    return book


# -- invariant checks (self-contained; mirrors tests/test_invariants.py) --

def assert_book_valid(book: OrderBook) -> None:
    for side in (Side.BUY, Side.SELL):
        depth = book.depth(side)
        prices = [p for p, _, _ in depth]
        expected = sorted(prices, reverse=(side is Side.BUY))
        assert prices == expected, f"{side} price levels not sorted correctly"
        for price, total_qty, _ in depth:
            level = book.get_level(side, price)
            summed = 0
            for o in level:
                assert 0 < o.remaining_quantity <= o.quantity
                assert book.get_order(o.order_id) is o
                summed += o.remaining_quantity
            assert summed == total_qty

    assert not book.is_crossed()


# -- benchmark ------------------------------------------------------------

def run_one(n: int, rng: random.Random) -> CancellationResult:
    book = build_resting_book(n, rng)
    all_ids = [f"o{i}" for i in range(n)]
    rng.shuffle(all_ids)

    sample_size = min(1_000, n // 10) or min(n, 1)
    warmup_count = min(WARMUP_COUNT, max(0, n - sample_size))

    warmup_ids = all_ids[:warmup_count]
    sample_ids = all_ids[warmup_count:warmup_count + sample_size]

    # untimed warm-up: exercises the exact same lookup/unlink path once
    # before measurement, on orders that are excluded from the sample.
    for order_id in warmup_ids:
        book.cancel_order(order_id)

    n_before_measurement = len(book)

    latencies_ns: List[int] = []
    for order_id in sample_ids:
        t0 = time.perf_counter_ns()
        book.cancel_order(order_id)
        t1 = time.perf_counter_ns()
        latencies_ns.append(t1 - t0)

    # -- verification -------------------------------------------------
    for order_id in sample_ids:
        assert order_id not in book, f"{order_id} should have been cancelled"
    assert len(book) == n_before_measurement - len(sample_ids)
    assert_book_valid(book)

    return CancellationResult(n_resting=n, samples=len(sample_ids), latencies_ns=latencies_ns)


def format_int(n: int) -> str:
    return f"{n:,}"


def run_benchmark(seed: int) -> None:
    sizes = [1_000, 10_000, 50_000, 100_000]
    rng = random.Random(seed)

    results: List[CancellationResult] = []
    for n in sizes:
        print(f"Building book with {n:,} resting orders (seed={seed})...")
        result = run_one(n, rng)
        results.append(result)
        print(
            f"  -> {result.samples:,} cancellations verified, book left with "
            f"{n - result.samples:,} resting orders, invariants hold."
        )

    print()
    header = f"{'N resting':<12}{'samples':<12}{'median_us':<12}{'mean_us':<12}{'p95_us':<12}{'total_us':<14}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{format_int(r.n_resting):<12}{format_int(r.samples):<12}"
            f"{r.median_us:<12.2f}{r.mean_us:<12.2f}{r.p95_us:<12.2f}{r.total_time_us:<14.1f}"
        )

    print(
        "\nNote: this measures the existing implementation only. Roughly flat "
        "latency across N is consistent with the dict-lookup + doubly-linked-"
        "list-unlink design being effectively O(1) per cancellation, but "
        "Python object/dict overhead, allocator behavior, and CPU caching mean "
        "this table is an empirical observation, not a proof of O(1)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cancellation latency as book size scales.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_benchmark(args.seed)


if __name__ == "__main__":
    main()
