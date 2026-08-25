import io

from limit_order_book import OrderBook, Side, parse_line, run_stream


def test_parse_line_limit():
    cmd = parse_line("LIMIT,a,BUY,1000,50")
    assert cmd == {"action": "LIMIT", "order_id": "a", "side": Side.BUY, "price": 1000, "quantity": 50}


def test_parse_line_market():
    cmd = parse_line("MARKET,a,SELL,20")
    assert cmd == {"action": "MARKET", "order_id": "a", "side": Side.SELL, "quantity": 20}


def test_parse_line_cancel():
    assert parse_line("CANCEL,a") == {"action": "CANCEL", "order_id": "a"}


def test_parse_line_modify_both_fields():
    cmd = parse_line("MODIFY,a,1001,30")
    assert cmd == {"action": "MODIFY", "order_id": "a", "new_price": 1001, "new_quantity": 30}


def test_parse_line_modify_blank_field_means_unchanged():
    cmd = parse_line("MODIFY,a,,30")
    assert cmd["new_price"] is None
    assert cmd["new_quantity"] == 30


def test_parse_line_ignores_blank_and_comment_lines():
    assert parse_line("") is None
    assert parse_line("   ") is None
    assert parse_line("# a comment") is None


def test_parse_line_rejects_garbage():
    from limit_order_book import ParseError
    import pytest

    with pytest.raises(ParseError):
        parse_line("LIMIT,a,BUY,not-a-number,50")
    with pytest.raises(ParseError):
        parse_line("FROBNICATE,a")


def test_run_stream_end_to_end_reports_trades_and_final_state():
    book = OrderBook()
    lines = [
        "# seed the book",
        "LIMIT,a,BUY,1000,100",
        "LIMIT,d,SELL,1005,50",
        "LIMIT,h,BUY,1005,30",  # crosses -> trade
        "CANCEL,a",
        "",
    ]
    out = io.StringIO()
    run_stream(book, lines, out=out)
    output = out.getvalue()

    assert "TRADE 30@1005 maker=d taker=h" in output
    assert "OK CANCEL a" in output
    assert "-- final book state --" in output
    assert "a" not in book
    assert book.get_order("d").remaining_quantity == 20  # 50 - 30, partially filled


def test_run_stream_reports_rejection_and_continues():
    b = OrderBook()
    lines = [
        "LIMIT,a,BUY,1000,50",
        "LIMIT,a,BUY,1000,50",  # duplicate id -> rejected, must not crash the stream
        "LIMIT,b,BUY,999,10",   # this must still be processed
    ]
    out = io.StringIO()
    run_stream(b, lines, out=out)
    output = out.getvalue()

    assert "REJECTED" in output
    assert "OK LIMIT b" in output
    assert "b" in b
