"""Stage 6 sanity checks: the synthetic flow generator produces well-formed
events, and -- reusing the Stage 5 invariant checks -- actually applying a
generated flow to a real book never violates any invariant. This is a
smoke test for the benchmarking tooling, not a performance assertion:
timing thresholds are intentionally not tested here since wall-clock
numbers vary by machine and would make CI flaky."""

from benchmarks.generate_flow import FlowConfig, generate_order_flow

from limit_order_book import DuplicateOrderId, InvalidOrder, OrderBook, UnknownOrderId, apply_command

from test_invariants import assert_all_invariants


def test_generate_order_flow_produces_well_formed_events():
    events = generate_order_flow(FlowConfig(num_events=200, seed=1))
    assert len(events) == 200
    for e in events:
        assert e["action"] in ("LIMIT", "MARKET", "CANCEL", "MODIFY")
        if e["action"] == "LIMIT":
            assert e["price"] > 0
            assert e["quantity"] > 0
        if e["action"] == "MARKET":
            assert e["quantity"] > 0


def test_applying_synthetic_flow_never_violates_invariants():
    events = generate_order_flow(FlowConfig(num_events=2000, seed=99))
    book = OrderBook()
    for event in events:
        try:
            apply_command(book, event)
        except (InvalidOrder, DuplicateOrderId, UnknownOrderId):
            pass
        assert_all_invariants(book)
