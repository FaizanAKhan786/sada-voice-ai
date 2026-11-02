"""Safe, deterministic customer-support workflows for the SADA demo.

All orders and policies are synthetic examples. Never connect this module to
real customer data without authentication and authorization.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

ORDERS: dict[str, dict[str, str]] = {
    "ORD-1001": {"item": "Wireless Headphones", "status": "In transit", "eta": "November 5, 2026", "tracking": "DEMO-73921"},
    "ORD-1002": {"item": "Smart Watch", "status": "Delivered", "eta": "October 30, 2026", "tracking": "DEMO-84603"},
    "ORD-1003": {"item": "Laptop Stand", "status": "Preparing for dispatch", "eta": "November 6, 2026", "tracking": "Not assigned"},
}
POLICIES = {
    "returns": "Demo returns policy: unused items may be returned within 30 days of delivery. Keep the original packaging and receipt. Exceptions may apply.",
    "refunds": "Demo refunds policy: once an eligible return is approved, a refund is typically processed within 5–7 business days. Your bank may take longer.",
    "shipping": "Demo shipping policy: standard deliveries usually arrive 3–5 business days after dispatch. You can check an order with its ID, for example ORD-1001.",
}
ARABIC = {
    "returns": "سياسة الإرجاع التجريبية: يمكن إرجاع المنتجات غير المستخدمة خلال 30 يوماً من التسليم مع العبوة الأصلية والإيصال. قد توجد استثناءات.",
    "refunds": "سياسة استرداد المبلغ التجريبية: بعد الموافقة على الإرجاع، تتم معالجة المبلغ عادةً خلال 5 إلى 7 أيام عمل وقد يحتاج البنك إلى وقت إضافي.",
    "shipping": "سياسة الشحن التجريبية: تصل الطلبات عادةً خلال 3 إلى 5 أيام عمل بعد الشحن. يمكنك الاستعلام باستخدام رقم مثل ORD-1001.",
}

AR_NUMERALS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ORDER_RE = re.compile(r"\bORD[\s\-]?([0-9]{4,6})\b", re.I)


def extract_order_id(text: str) -> str | None:
    match = ORDER_RE.search(text.translate(AR_NUMERALS))
    return f"ORD-{match.group(1)}" if match else None


def detect_language(text: str, selected: str = "auto") -> str:
    if selected in {"en", "ar"}:
        return selected
    return "ar" if re.search(r"[\u0600-\u06FF]", text) else "en"


def classify_intent(text: str, awaiting_order: bool = False) -> str:
    t = text.lower().translate(AR_NUMERALS)
    # An order reference in a follow-up should complete the workflow.
    if awaiting_order and extract_order_id(t):
        return "order_status"
    patterns = [
        ("handoff", r"\b(human|person|representative|live agent|supervisor|talk to agent|escalat\w*)\b|موظف|بشري|تحويل|خدمة العملاء|ممثل"),
        ("refunds", r"\b(refunds?|money back|reimburse\w*)\b|استرداد|استرجاع المبلغ|استعادة المبلغ"),
        ("returns", r"\b(returns?|exchanges?|replacement)\b|إرجاع|ارجاع|تبديل|استبدال|اعادة"),
        ("order_status", r"\b(order|track|tracking|delivery status|where is|shipment|parcel)\b|طلب|طلبي|شحنة|شحن|تتبع|وصل|وين"),
        ("shipping", r"\b(shipping|delivery time|ship time|how long)\b|مدة التوصيل|متى التوصيل"),
        ("greeting", r"^\s*(hi|hello|hey|good morning|good evening|مرحبا|مرحباً|السلام عليكم|اهلا|أهلا|هلا)[!?.\s]*$"),
    ]
    for name, expression in patterns:
        if re.search(expression, t, re.I):
            return name
    if extract_order_id(t):
        return "order_status"
    return "general"


@dataclass
class Session:
    language: str = "auto"
    awaiting_order: bool = False
    last_order_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Answer:
    text: str
    intent: str
    language: str
    handoff: bool = False
    case_id: str | None = None
    order_id: str | None = None
    source: str = "demo_policy"
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_message(text: str, session: Session) -> Answer:
    """One safe deterministic turn; no external actions or real customer data."""
    text = text.strip()
    if not text:
        raise ValueError("Message must not be empty")
    if len(text) > 1500:
        raise ValueError("Message is too long (maximum 1500 characters)")

    lang = detect_language(text, session.language)
    intent = classify_intent(text, session.awaiting_order)
    order_id = extract_order_id(text)

    if intent == "handoff":
        case_id = "CASE-" + uuid.uuid4().hex[:8].upper()
        response = (f"I've created a DEMO handoff request {case_id}. In a real deployment, a verified support agent would take over. No live team is connected in this demo."
                    if lang == "en" else f"تم إنشاء طلب تحويل تجريبي برقم {case_id}. في النسخة الحقيقية سيتولى موظف الدعم المحادثة، ولا يوجد فريق متصل بهذا العرض.")
        result = Answer(response, intent, lang, handoff=True, case_id=case_id, source="demo_handoff")
    elif intent == "order_status":
        order_id = order_id or session.last_order_id
        if not order_id:
            session.awaiting_order = True
            response = "Sure. What's your demo order number? Try ORD-1001, ORD-1002 or ORD-1003." if lang == "en" else "بالتأكيد. ما رقم طلبك التجريبي؟ يمكنك تجربة ORD-1001 أو ORD-1002 أو ORD-1003."
            result = Answer(response, intent, lang, source="demo_orders")
        elif order_id not in ORDERS:
            session.awaiting_order = True
            response = f"I couldn't find {order_id} in the demo orders. Try ORD-1001, ORD-1002 or ORD-1003." if lang == "en" else f"لم أجد الطلب {order_id} في بيانات التجربة. جرّب ORD-1001 أو ORD-1002 أو ORD-1003."
            result = Answer(response, intent, lang, order_id=order_id, source="demo_orders")
        else:
            session.awaiting_order = False
            session.last_order_id = order_id
            order = ORDERS[order_id]
            response = (f"{order_id}: {order['item']} is **{order['status']}**. Delivery estimate/date: {order['eta']}. Tracking: {order['tracking']}. These are sample records."
                        if lang == "en" else f"الطلب {order_id}: المنتج {order['item']}. الحالة: **{order['status']}**. موعد التسليم: {order['eta']}. رقم التتبع: {order['tracking']}. هذه بيانات تجريبية.")
            result = Answer(response, intent, lang, order_id=order_id, source="demo_orders")
    elif intent in {"returns", "refunds", "shipping"}:
        session.awaiting_order = False
        response = ARABIC[intent] if lang == "ar" else POLICIES[intent]
        result = Answer(response, intent, lang, source="demo_policy")
    elif intent == "greeting":
        session.awaiting_order = False
        response = "Hello! I'm SADA, your demo voice support assistant. I can track sample orders, explain returns and refunds, or create a demo handoff request." if lang == "en" else "مرحباً! أنا صدى، مساعد خدمة العملاء التجريبي. أساعدك في تتبع الطلبات التجريبية، والإرجاع، واسترداد الأموال، أو طلب التحويل لموظف."
        result = Answer(response, intent, lang, source="scripted")
    else:
        session.awaiting_order = False
        response = "I can help with demo order tracking, returns, refunds and shipping. Ask for a human agent to create a demo handoff. I won't guess other account details." if lang == "en" else "يمكنني المساعدة في تتبع الطلبات التجريبية، والإرجاع، واسترداد المبالغ، والشحن. ويمكنك طلب موظف لتحويل تجريبي. لن أخمّن أي معلومات خاصة بالحسابات."
        result = Answer(response, intent, lang, source="scripted")

    session.history.extend([{"role": "user", "text": text}, {"role": "assistant", "text": result.text}])
    session.history = session.history[-20:]
    return result
