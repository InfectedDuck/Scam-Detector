"""PII detection and masking.

One implementation, two consumers:

* `extract.py` masks values the moment they are detected, so an `Entities`
  object never holds a card number or a national identification number.
* The dataset scrubber (T405) runs `scrub` over corpus rows before a human
  ever reads them.

Amounts and institution names are deliberately **not** scrubbed. They are
semantic content, and removing them would destroy the signal the corpus exists
to capture. See docs/05_EVAL_PROTOCOL.md section 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from saqbol.core.patterns import (
    AMOUNT_PREFIX,
    AMOUNT_SUFFIX,
    CARD,
    EMAIL,
    HANDLE,
    IIN,
    PHONE,
    SpanClaim,
    is_phone_shaped,
    luhn,
)

PLACEHOLDER = {
    "card": "<CARD>",
    "iin": "<IIN>",
    "phone": "<PHONE>",
    "email": "<EMAIL>",
    "handle": "<HANDLE>",
}


@dataclass
class ScrubResult:
    text: str
    applied: list[str] = field(default_factory=list)


def mask_card(value: str) -> str:
    """Cards are replaced by their length alone.

    The presence of a card number matters to a scam verdict. Its value does
    not, and the safest field is an absent one.
    """
    return f"<CARD:{sum(1 for c in value if c.isdigit())}>"


def find_cards(text: str) -> list[str]:
    """Luhn-valid card numbers, returned already masked."""
    return [mask_card(m.group(0)) for m in CARD.finditer(text) if luhn(m.group(0))]


def find_iins(text: str) -> list[str]:
    """Kazakhstani individual identification numbers, returned masked."""
    return [PLACEHOLDER["iin"] for _ in IIN.finditer(text)]


def scrub(text: str) -> ScrubResult:
    """Replace every PII class with a typed placeholder.

    Placeholders are typed rather than blanked so the text stays linguistically
    usable: a model can still learn that a message asked for *a card number*.

    Priority order matters. Amounts are reserved first so that a large tenge
    figure is never masked as a telephone number, and cards are matched before
    phones because a spaced sixteen-digit group satisfies both patterns.
    """
    claim = SpanClaim()
    claim.reserve(AMOUNT_SUFFIX, text)
    claim.reserve(AMOUNT_PREFIX, text)

    applied: list[str] = []
    edits: list[tuple[int, int, str]] = []

    ordered = (
        (CARD, "card", luhn),
        (IIN, "iin", None),
        (EMAIL, "email", None),
        (PHONE, "phone", is_phone_shaped),
        (HANDLE, "handle", None),
    )

    for pattern, label, guard in ordered:
        for m in pattern.finditer(text):
            if guard is not None and not guard(m.group(0)):
                continue
            if not claim.claim(m.start(), m.end()):
                continue
            edits.append((m.start(), m.end(), PLACEHOLDER[label]))
            if label not in applied:
                applied.append(label)

    out = []
    cursor = 0
    for start, end, token in sorted(edits):
        out.append(text[cursor:start])
        out.append(token)
        cursor = end
    out.append(text[cursor:])

    return ScrubResult(text="".join(out), applied=applied)


def contains_unmasked_pii(text: str) -> bool:
    """Assertion helper for tests and for the pre-write check on any row."""
    if any(luhn(m.group(0)) for m in CARD.finditer(text)):
        return True
    return bool(IIN.search(text) or EMAIL.search(text))
