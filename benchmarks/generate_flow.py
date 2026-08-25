"""Synthetic order-flow generator for Stage 6 benchmarking.

Produces a fixed, pre-generated list of order-entry command dicts -- the
same shape io_adapter.parse_line() produces, so the same apply_command()
used by Stage 4 can run them directly. Generated up front (not streamed
lazily) so that timing the engine in bench_throughput.py doesn't also time
random-number generation.

Prices random-walk around a starting mid-price so the flow looks roughly
like real quote activity clustering near a moving market, rather than
being scattered uniformly across all possible prices.

Note on CANCEL/MODIFY targets: this generator tracks "orders it told to
submit as LIMIT" as candidates for a later cancel/modify, but it doesn't
actually run the matching engine to know which of those got fully filled
(or swept away by a later aggressive order) before the cancel/modify would
apply. Re-simulating the whole engine just to generate a workload for the
engine would be redundant. In practice this means some generated CANCEL/
MODIFY events will be rejected as UnknownOrderId when actually applied --
which is realistic (real order flow has cancel-after-fill races too) and
already handled by apply_command's rejection path, so it's harmless.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from limit_order_book import Side


@dataclass
class FlowConfig:
    num_events: int = 100_000
    seed: int = 42
    starting_mid_price: int = 10_000
    max_walk_step: int = 2  # mid-price random walk step per event, in ticks
    max_offset_from_mid: int = 20  # how far a limit price can sit from mid, in ticks
    max_quantity: int = 100
    p_limit: float = 0.65
    p_market: float = 0.10
    p_cancel: float = 0.20
    p_modify: float = 0.05


def generate_order_flow(config: FlowConfig = FlowConfig()) -> List[dict]:
    rng = random.Random(config.seed)
    mid = config.starting_mid_price
    live_ids: List[str] = []
    events: List[dict] = []
    next_id = 0

    actions = ["limit", "market", "cancel", "modify"]
    weights = [config.p_limit, config.p_market, config.p_cancel, config.p_modify]

    for _ in range(config.num_events):
        mid += rng.randint(-config.max_walk_step, config.max_walk_step)
        mid = max(mid, config.max_offset_from_mid + 1)  # keep prices positive

        action = rng.choices(actions, weights=weights, k=1)[0]
        if action in ("cancel", "modify") and not live_ids:
            action = "limit"

        if action == "limit":
            order_id = f"o{next_id}"
            next_id += 1
            side = rng.choice([Side.BUY, Side.SELL])
            offset = rng.randint(1, config.max_offset_from_mid)
            price = mid - offset if side is Side.BUY else mid + offset
            quantity = rng.randint(1, config.max_quantity)
            events.append({
                "action": "LIMIT", "order_id": order_id,
                "side": side, "price": price, "quantity": quantity,
            })
            live_ids.append(order_id)

        elif action == "market":
            order_id = f"o{next_id}"
            next_id += 1
            side = rng.choice([Side.BUY, Side.SELL])
            quantity = rng.randint(1, config.max_quantity)
            events.append({
                "action": "MARKET", "order_id": order_id,
                "side": side, "quantity": quantity,
            })

        elif action == "cancel":
            # Picking by index and swap-popping (instead of rng.choice() +
            # live_ids.remove(value)) avoids an O(n) linear scan to find
            # the value -- the exact deque.remove()-style trap from the
            # design doc's section 3, just showing up here in the
            # generator instead of the engine. Order within live_ids
            # doesn't matter, so this is a safe O(1) removal.
            idx = rng.randrange(len(live_ids))
            order_id = live_ids[idx]
            live_ids[idx] = live_ids[-1]
            live_ids.pop()
            events.append({"action": "CANCEL", "order_id": order_id})

        else:  # modify
            order_id = rng.choice(live_ids)
            new_price = mid + rng.randint(-5, 5) if rng.random() < 0.5 else None
            new_quantity = rng.randint(1, config.max_quantity) if rng.random() < 0.5 else None
            if new_price is None and new_quantity is None:
                new_quantity = rng.randint(1, config.max_quantity)
            events.append({
                "action": "MODIFY", "order_id": order_id,
                "new_price": new_price, "new_quantity": new_quantity,
            })

    return events
