"""Shared regular expressions and span arbitration.

Single source of truth. `privacy.py` and `extract.py` both consume these, so a
pattern can never drift between the masker and the extractor.

Digit runs are deeply ambiguous in this domain. A twelve-digit national
identification number also satisfies a loose phone pattern; a tenge amount also
satisfies it; a card number contains four groups that each look like a short
code. Matching each pattern independently therefore produces overlapping,
contradictory entities. `SpanClaim` resolves that by priority: the first
pattern to claim a region of text owns it.
"""

from __future__ import annotations

import regex as re

# --- identifiers -----------------------------------------------------------

CARD = re.compile(r"(?<![\d])(?:\d[ \-]?){12,18}\d(?![\d])")
IIN = re.compile(r"(?<![\d])\d{12}(?![\d])")
PHONE = re.compile(r"(?<![\d\w])(?:\+?\d[\d\s\-().]{5,17}\d)(?![\d])")
SHORT_CODE = re.compile(r"(?<![\d\w])(\d{3,5})(?![\d])")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
HANDLE = re.compile(r"(?<![\w/])@[A-Za-z][A-Za-z0-9_]{4,31}")

PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15

# --- money -----------------------------------------------------------------

CURRENCY_WORDS = (
    r"тг|тнг|тенге|теңге|₸|KZT|"
    r"руб\w*|₽|RUB|"
    r"\$|USD|доллар\w*|"
    r"¥|CNY|юан\w*|元|"
    r"€|EUR|евро"
)
AMOUNT_SUFFIX = re.compile(rf"\d[\d\s.,]*\s*(?:{CURRENCY_WORDS})", re.IGNORECASE)
AMOUNT_PREFIX = re.compile(rf"(?:{CURRENCY_WORDS})\s*\d[\d\s.,]*", re.IGNORECASE)

# --- links -----------------------------------------------------------------

SCHEME_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
WWW_URL = re.compile(r"(?<![@\w])www\.[^\s<>\"']+", re.IGNORECASE)
# Unicode letter classes, so homograph domains such as "kaspі.kz" are caught.
BARE_DOMAIN = re.compile(
    r"(?<![@\w./])((?:[\p{L}\p{N}][\p{L}\p{N}-]*\.)+[\p{L}]{2,24})(?:/[^\s<>\"']*)?"
)
APK = re.compile(r"\.apk\b", re.IGNORECASE)

CRYPTO = [
    re.compile(r"(?<![\w])bc1[a-z0-9]{25,62}(?![\w])"),
    re.compile(r"(?<![\w])[13][a-km-zA-HJ-NP-Z1-9]{25,34}(?![\w])"),
    re.compile(r"(?<![\w])0x[a-fA-F0-9]{40}(?![\w])"),
    re.compile(r"(?<![\w])T[A-Za-z1-9]{33}(?![\w])"),
]

URL_TRAILING = ".,;:!?)»\"'"


def luhn(digits: str) -> bool:
    """Standard Luhn checksum. Keeps order numbers out of the card set."""
    ds = [int(c) for c in digits if c.isdigit()]
    if len(ds) < 12:
        return False
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def digit_count(value: str) -> int:
    return sum(1 for c in value if c.isdigit())


def is_phone_shaped(value: str) -> bool:
    return PHONE_MIN_DIGITS <= digit_count(value) <= PHONE_MAX_DIGITS


class SpanClaim:
    """First-come ownership of character ranges.

    Patterns are offered in priority order. A later, weaker pattern cannot
    re-interpret text that a stronger one already explained.
    """

    def __init__(self) -> None:
        self._spans: list[tuple[int, int]] = []

    def free(self, start: int, end: int) -> bool:
        return not any(start < e and end > s for s, e in self._spans)

    def claim(self, start: int, end: int) -> bool:
        if not self.free(start, end):
            return False
        self._spans.append((start, end))
        return True

    def reserve(self, pattern: re.Pattern, text: str) -> None:
        """Claim every match of `pattern` without producing entities.

        Used to protect monetary amounts before phone matching runs, so
        "480 000 тенге" is never read as a telephone number.
        """
        for m in pattern.finditer(text):
            self.claim(m.start(), m.end())

    @property
    def spans(self) -> list[tuple[int, int]]:
        return sorted(self._spans)
