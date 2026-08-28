"""Deterministic natural-language intent parsing.

A keyword parser, not a pretence at understanding. It exists so the intent contract is
populated — and the whole system testable — with no API key present. When the semantic
layer is configured it refines the ``purpose`` and mismatch judgement on top; it never
becomes a prerequisite.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.schemas.entities import IntentContract
from app.schemas.enums import MerchantPolicy

CATEGORY_KEYWORDS = {
    "grocery": ["grocery", "groceries", "supermarket", "vegetables", "kirana"],
    "food": ["food", "meal", "restaurant", "takeaway", "lunch", "dinner"],
    "electronics": ["electronics", "laptop", "phone", "gadget", "headphones"],
    "fashion": ["clothes", "clothing", "fashion", "shoes", "apparel"],
    "pharmacy": ["medicine", "pharmacy", "chemist", "prescription"],
    "travel": ["travel", "flight", "hotel", "ticket", "trip"],
    "gaming": ["game", "gaming", "console"],
    "utilities": ["bill", "utility", "electricity", "recharge", "broadband"],
    "alcohol": ["alcohol", "beer", "wine", "liquor"],
    "gift_cards": ["gift card", "voucher", "gift voucher"],
}

NEGATION_PATTERN = re.compile(
    r"(?:don'?t|do not|never|no|avoid|without|except|excluding)\s+(?:buy|purchase|get|order)?\s*"
    r"(?:any\s+)?([a-z_ ]{3,40})",
    re.I,
)
AMOUNT_PATTERN = re.compile(
    r"(?:under|below|less than|max(?:imum)?|up to|not more than|cap(?:ped)? at)\s*"
    r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)


def parse_instruction(text: str | None, *, valid_days: int = 30) -> IntentContract | None:
    """Extract a structured contract from a natural-language instruction.

    Returns ``None`` for empty input rather than an empty contract: an absent instruction
    and an instruction that constrains nothing are different situations.
    """
    if not text or not text.strip():
        return None

    lowered = text.lower()
    allowed: list[str] = []
    forbidden: list[str] = []

    negated_spans = [m.group(1).lower() for m in NEGATION_PATTERN.finditer(lowered)]

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword not in lowered:
                continue
            if any(keyword in span for span in negated_spans):
                if category not in forbidden:
                    forbidden.append(category)
            elif category not in allowed:
                allowed.append(category)
            break

    allowed = [c for c in allowed if c not in forbidden]

    max_amount: Decimal | None = None
    match = AMOUNT_PATTERN.search(lowered)
    if match:
        try:
            max_amount = Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
        except InvalidOperation:
            max_amount = None

    policy = MerchantPolicy.KNOWN_OR_APPROVED
    if any(phrase in lowered for phrase in ("any store", "any merchant", "anywhere")):
        policy = MerchantPolicy.ANY
    elif any(phrase in lowered for phrase in ("only from", "allowlist", "approved store")):
        policy = MerchantPolicy.ALLOWLIST_ONLY

    purpose = f"{allowed[0]}_purchase" if allowed else "general_purchase"

    return IntentContract(
        purpose=purpose,
        max_amount=max_amount,
        currency="INR",
        allowed_categories=allowed,
        forbidden_categories=forbidden,
        merchant_policy=policy,
        approval_required_above=max_amount,
        valid_until=datetime.now(UTC) + timedelta(days=valid_days),
        source_text=text[:2000],
    )
