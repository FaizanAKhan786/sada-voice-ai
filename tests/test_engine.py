from app.engine import Session, classify_intent, detect_language, extract_order_id, route_message


def test_english_order_flow():
    s = Session()
    first = route_message("Where is my order?", s)
    assert first.intent == "order_status" and s.awaiting_order
    follow = route_message("ORD-1001", s)
    assert follow.order_id == "ORD-1001" and "In transit" in follow.text
    assert not s.awaiting_order


def test_arabic_digit_and_language():
    assert extract_order_id("طلبي ORD-١٠٠٢") == "ORD-1002"
    s = Session()
    answer = route_message("وين طلبي ORD-١٠٠٢؟", s)
    assert answer.language == "ar" and answer.order_id == "ORD-1002"


def test_policy_is_fictional_and_localized():
    a = route_message("What is the refund policy?", Session())
    b = route_message("كيف يمكن استرداد المبلغ؟", Session())
    assert a.intent == b.intent == "refunds"
    assert "Demo" in a.text and "التجريبية" in b.text


def test_handoff_is_demo_only():
    answer = route_message("Can I talk to a human agent?", Session())
    assert answer.handoff is True and answer.case_id.startswith("CASE-")
    assert "No live team" in answer.text


def test_missing_unknown_order():
    s = Session()
    reply = route_message("Track ORD-9999", s)
    assert "couldn't find" in reply.text
    assert s.awaiting_order


def test_language_override_and_intents():
    assert detect_language("Hello", "ar") == "ar"
    assert classify_intent("Tell me about returns") == "returns"
    assert classify_intent("shipping rates") == "shipping"


def test_input_validation():
    import pytest
    with pytest.raises(ValueError):
        route_message(" ", Session())
    with pytest.raises(ValueError):
        route_message("x" * 1501, Session())


def test_session_history_bounded():
    s = Session()
    for _ in range(15):
        route_message("hello", s)
    assert len(s.history) == 20
