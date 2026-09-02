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

--------------------------------------------------------------------------
NAIVE PYTHON-LIST BASELINE (benchmark-only, added for comparison)
--------------------------------------------------------------------------
Alongside the real engine, this script now measures a deliberately naive
cancel-by-id structure: a plain `list[NaiveOrder]` with NO auxiliary dict
or index. Cancellation walks the list to find the target id and then
`del`s it:

    for i, order in enumerate(orders):
        if order.order_id == target_id:
            del orders[i]
            break

This baseline pays TWO linear-cost effects per cancellation:

  1. scanning the list to locate the target order (O(n) comparisons); with
     targets drawn from a shuffled id pool, the target sits at a uniformly
     random position, so the scan is ~n/2 on average -- the representative
     case, not the best (front) or worst (back) case.
  2. `del orders[i]` from the middle of a Python list, which shifts every
     subsequent element down one slot (a C-level memmove, fast per element
     but still O(n) work).

It is therefore specifically a comparison against a simple list-based
design. It is NOT a claim that every alternative to the engine's
architecture must be O(n): a different data structure (e.g. a hash index,
a tree, an order-id -> node map of any kind) would scale differently. See
the interpretation caveat printed at the end.

Fairness: for each N the naive list is snapshotted from the freshly built
real book *before any cancellation*, so both structures hold the exact
same population -- same order_id, side, price, quantity, in the same
insertion order -- and every sampled target id is known to exist in both.
The two benchmarks are run in fully separate loops over independent data,
so timing one never touches the state of the other. Building the snapshot
consumes no RNG, so the real-engine measurement sees exactly the same
draws it would without the baseline present.

Run: PYTHONPATH=. python benchmarks/bench_cancellation.py [--seed S]
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import time
from dataclasses import dataclass
from typing import List, Tuple

from limit_order_book import Order, OrderBook, Side, submit_limit_order

BUY_PRICE_LOW, BUY_PRICE_HIGH = 9_500, 9_999
SELL_PRICE_LOW, SELL_PRICE_HIGH = 10_001, 10_500
MAX_QUANTITY = 100
WARMUP_COUNT = 20


@dataclass
class CancellationResult:
    label: str
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


# -- naive list baseline (benchmark-only; not used by the engine) ------

@dataclass(slots=True)
class NaiveOrder:
    """One entry in the naive list. Holds the minimum a cancel-by-id
    structure needs to identify and describe an order. Intentionally has
    no back-pointer, no price-level handle, nothing that would let removal
    skip the scan -- that is the whole point of the baseline."""

    order_id: str
    side: Side
    price: int
    quantity: int


def snapshot_naive_list(book: OrderBook, n: int) -> List[NaiveOrder]:
    """Build a plain list mirroring the book's resting orders, in the same
    insertion order ("o0".."o{n-1}"). Called before any cancellation, so
    it captures the full population. Reads from the already-built book and
    draws no random numbers, so it cannot perturb the real-engine RNG
    stream or the book's state."""
    naive: List[NaiveOrder] = []
    for i in range(n):
        o = book.get_order(f"o{i}")
        assert o is not None, "snapshot must run before any cancellation"
        naive.append(NaiveOrder(o.order_id, o.side, o.price, o.remaining_quantity))
    return naive


def naive_cancel(orders: List[NaiveOrder], target_id: str) -> bool:
    """Deliberately naive cancel-by-id. Two linear-cost effects per call
    (see module docstring): the enumerate() scan to locate `target_id`,
    and `del orders[i]` shifting every later element down one slot.
    Returns True if the id was found and removed."""
    for i, order in enumerate(orders):
        if order.order_id == target_id:
            del orders[i]
            return True
    return False


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

def _sampling_plan(n: int, rng: random.Random) -> Tuple[List[str], List[str]]:
    """Reproduce the existing benchmark's id selection exactly: shuffle the
    full id pool with the shared RNG, peel off an untimed warm-up batch,
    then the timed sample. Returns (warmup_ids, sample_ids)."""
    all_ids = [f"o{i}" for i in range(n)]
    rng.shuffle(all_ids)

    sample_size = min(1_000, n // 10) or min(n, 1)
    warmup_count = min(WARMUP_COUNT, max(0, n - sample_size))

    warmup_ids = all_ids[:warmup_count]
    sample_ids = all_ids[warmup_count:warmup_count + sample_size]
    return warmup_ids, sample_ids


def measure_real_engine(
    book: OrderBook, warmup_ids: List[str], sample_ids: List[str], n: int
) -> CancellationResult:
    """Time cancel_order() on the real book: dict lookup + doubly-linked-
    list unlink, no scan over resting orders. Warm-up and verification are
    untimed."""
    for order_id in warmup_ids:  # untimed warm-up: same lookup/unlink path
        book.cancel_order(order_id)

    n_before_measurement = len(book)

    latencies_ns: List[int] = []
    for order_id in sample_ids:
        t0 = time.perf_counter_ns()
        book.cancel_order(order_id)
        t1 = time.perf_counter_ns()
        latencies_ns.append(t1 - t0)

    # -- correctness -----------------------------------------------------
    for order_id in sample_ids:
        assert order_id not in book, f"{order_id} should have been cancelled"
    assert len(book) == n_before_measurement - len(sample_ids)
    assert_book_valid(book)

    return CancellationResult(
        label="engine", n_resting=n, samples=len(sample_ids), latencies_ns=latencies_ns
    )


def measure_naive_list(
    naive: List[NaiveOrder], warmup_ids: List[str], sample_ids: List[str], n: int
) -> CancellationResult:
    """Time naive_cancel() on a plain list: linear scan to find the id plus
    a middle `del` that shifts the tail. Run on its own independent list so
    it shares no state with the real-engine measurement. Warm-up and
    verification are untimed."""
    for order_id in warmup_ids:  # untimed warm-up: same scan + del path
        assert naive_cancel(naive, order_id), f"{order_id} missing during warm-up"

    n_before_measurement = len(naive)

    found: List[bool] = []
    latencies_ns: List[int] = []
    for order_id in sample_ids:
        t0 = time.perf_counter_ns()
        ok = naive_cancel(naive, order_id)
        t1 = time.perf_counter_ns()
        latencies_ns.append(t1 - t0)
        found.append(ok)

    # -- correctness -----------------------------------------------------
    assert all(found), "every sampled naive cancellation must have found its target"
    assert len(naive) == n_before_measurement - len(sample_ids)
    remaining_ids = {o.order_id for o in naive}
    assert remaining_ids.isdisjoint(sample_ids), "cancelled id still present in naive list"

    return CancellationResult(
        label="naive", n_resting=n, samples=len(sample_ids), latencies_ns=latencies_ns
    )


def run_one(n: int, rng: random.Random) -> Tuple[CancellationResult, CancellationResult]:
    """Build one real book and one equivalent naive list for size `n`, then
    measure each in a fully separate pass. Returns (engine_result,
    naive_result)."""
    book = build_resting_book(n, rng)
    warmup_ids, sample_ids = _sampling_plan(n, rng)

    # Snapshot the naive list from the pristine book -- before any cancel --
    # so both structures start from the identical population.
    naive = snapshot_naive_list(book, n)
    assert len(naive) == len(book) == n

    # Pass 1: the real engine, on its own book.
    engine_result = measure_real_engine(book, warmup_ids, sample_ids, n)

    # Pass 2: the naive list, on its own data. The engine's book is not
    # touched here; re-check it to prove the naive pass changed nothing.
    naive_result = measure_naive_list(naive, warmup_ids, sample_ids, n)
    assert_book_valid(book)
    left = n - len(warmup_ids) - len(sample_ids)
    assert len(book) == left == len(naive)
    print(
        f"  -> {engine_result.samples:,} cancellations verified on each structure; "
        f"engine book and naive list each left with {left:,} resting orders, "
        f"engine invariants hold."
    )

    return engine_result, naive_result


def format_int(n: int) -> str:
    return f"{n:,}"


def run_benchmark(seed: int) -> None:
    sizes = [1_000, 10_000, 50_000, 100_000]
    rng = random.Random(seed)

    rows: List[Tuple[CancellationResult, CancellationResult]] = []
    for n in sizes:
        print(f"Building book + naive list with {n:,} resting orders (seed={seed})...")
        engine_result, naive_result = run_one(n, rng)
        rows.append((engine_result, naive_result))

    # -- summary table -----------------------------------------------------
    print()
    print("Summary: cancellation latency vs. resting-book size")
    print()
    header = f"{'N resting':<12}| {'engine median us':<18}| {'naive median us':<18}| speedup"
    print(header)
    print("-" * len(header))
    for engine_result, naive_result in rows:
        speedup = naive_result.median_us / engine_result.median_us
        print(
            f"{format_int(engine_result.n_resting):<12}| "
            f"{engine_result.median_us:<18.2f}| "
            f"{naive_result.median_us:<18.2f}| "
            f"{speedup:,.1f}x"
        )
    print()
    print("speedup = naive_list_median_us / real_engine_median_us")

    # -- detailed mean / p95 breakdown ----------------------------------
    print()
    print("Detail: median / mean / p95 per cancellation (microseconds)")
    print()
    detail_header = (
        f"{'N resting':<12}{'samples':<10}"
        f"{'eng median':<12}{'eng mean':<12}{'eng p95':<12}"
        f"{'naive median':<14}{'naive mean':<14}{'naive p95':<14}"
    )
    print(detail_header)
    print("-" * len(detail_header))
    for engine_result, naive_result in rows:
        print(
            f"{format_int(engine_result.n_resting):<12}{format_int(engine_result.samples):<10}"
            f"{engine_result.median_us:<12.2f}{engine_result.mean_us:<12.2f}{engine_result.p95_us:<12.2f}"
            f"{naive_result.median_us:<14.2f}{naive_result.mean_us:<14.2f}{naive_result.p95_us:<14.2f}"
        )

    # -- interpretation caveat ----------------------------------------
    print(
        "\nInterpretation\n"
        "--------------\n"
        "- The real engine locates an order with a hash-indexed lookup\n"
        "  (dict[order_id] -> Order) and removes it by unlinking a node from a\n"
        "  doubly linked list it already holds a reference to. Neither step\n"
        "  scans the resting orders, so per-cancellation cost is ~flat as N grows.\n"
        "- The naive baseline intentionally uses a plain Python list and a\n"
        "  linear search for the id. On top of the scan, `del list[i]` from the\n"
        "  middle shifts every later element down one slot. Both effects grow\n"
        "  with N, so its per-cancellation cost -- and the speedup -- rises with N.\n"
        "- This demonstrates the scaling behaviour of these two specific designs.\n"
        "  It is NOT a claim that every real-world alternative to the engine's\n"
        "  architecture is O(n), nor that these microsecond timings 'prove' a\n"
        "  complexity class.\n"
        "- Big-O describes how algorithmic work scales; the measured numbers are\n"
        "  also shaped by Python interpreter overhead, CPU caching, memory\n"
        "  allocation, and system noise. The fixed cost of time.perf_counter_ns()\n"
        "  is a larger fraction of the engine's tiny cancel than of the naive\n"
        "  one, so the reported speedup is, if anything, conservative.\n"
        "- Only the existing engine is measured here; nothing in limit_order_book/\n"
        "  is modified, tuned, or exercised differently because of this baseline."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cancellation latency as book size scales.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_benchmark(args.seed)


if __name__ == "__main__":
    main()
