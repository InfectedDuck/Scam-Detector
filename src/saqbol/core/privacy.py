"""PII detection and masking.

One implementation, two consumers:

* `extract.py` masks values the moment they are detected, so an `Entities`
  object never holds a card number or a national identification number.
* `tools/scrub_corpus.py` runs `scrub` over every corpus row before a human
  ever reads it, and `contains_unmasked_pii` is the assertion behind the
  corpus test.

Regular expressions are the mechanism. They are deterministic, need no model
download and can be audited line by line, which is what a dataset release
needs. Presidio, or any other NER-based recogniser, is an optional second pass
to run before a public release for the classes no regex will catch (personal
names, street addresses). It is not a requirement of this module and nothing
here depends on it.

Amounts, short codes, dates and institution names are deliberately **not**
scrubbed. They are semantic content, and removing them would destroy the
signal the corpus exists to capture. See docs/05_EVAL_PROTOCOL.md section 2.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import regex as re

from saqbol.core.patterns import (
    CARD,
    CURRENCY_WORDS,
    EMAIL,
    HANDLE,
    IIN,
    PHONE,
    PHONE_MAX_DIGITS,
    SpanClaim,
    digit_count,
    is_phone_shaped,
    luhn,
)

__all__ = [
    "PLACEHOLDER",
    "PiiSpan",
    "ScrubResult",
    "contains_unmasked_pii",
    "find_cards",
    "find_iins",
    "find_pii",
    "luhn",
    "mask_card",
    "scrub",
]

PLACEHOLDER = {
    "card": "<CARD>",
    "iin": "<IIN>",
    "iban": "<IBAN>",
    "phone": "<PHONE>",
    "email": "<EMAIL>",
    "handle": "<HANDLE>",
}

# --- scrubber-only patterns ---------------------------------------------------
#
# `patterns.py` owns the shared vocabulary. The patterns below exist to make
# the scrubber stricter than the extractor in one direction only: nothing
# that identifies a person may survive, while nothing that is merely a
# number may disappear.

# Kazakhstani IBAN: "KZ", two check digits, sixteen alphanumerics (bank code
# and account). Banking apps show it bare; statements group it in fours.
IBAN = re.compile(r"(?<![\w])KZ\d{2}(?: ?[A-Z0-9]){16}(?![\w])", re.IGNORECASE)

_SEP = r"[\s\-.]*"

# Kazakhstan and Russia: +7 or 8, a 7XX or 9XX area code, then 3-2-2.
# Landline codes (727 Almaty, 717 Astana) have the same shape as mobiles.
KZ_PHONE = re.compile(
    rf"(?<![\d\w])(?:\+7|8){_SEP}\(?[79]\d{{2}}\)?{_SEP}\d{{3}}{_SEP}\d{{2}}{_SEP}\d{{2}}(?![\d])"
)

# China: optional +86 or 0086, a mobile prefix 13 to 19, then 3-4-4.
CN_PHONE = re.compile(rf"(?<![\d\w])(?:\+86|0086)?{_SEP}1[3-9]\d{_SEP}\d{{4}}{_SEP}\d{{4}}(?![\d])")

# A single monetary figure next to a currency word. `patterns.AMOUNT_SUFFIX`
# is looser (any digits, spaces and dots before the word), which suits the
# extractor but would let "87071234567 5000 тг" swallow the phone number.
_NUMBER = r"(?:\d{1,3}(?:[ .,]\d{3})+|\d+)(?:[.,]\d{1,2})?"
AMOUNT_BEFORE_CURRENCY = re.compile(rf"(?<![\d]){_NUMBER}\s*(?:{CURRENCY_WORDS})", re.IGNORECASE)
AMOUNT_AFTER_CURRENCY = re.compile(rf"(?:{CURRENCY_WORDS})\s*{_NUMBER}(?![\d])", re.IGNORECASE)

# Calendar dates are detection signal ("payment due 12.03.2025") and share a
# shape with dotted or dashed telephone numbers. Day and month are range
# checked so that a phone group such as "45-67" is never mistaken for one.
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_MONTH = r"(?:0?[1-9]|1[0-2])"
DATE = re.compile(
    rf"(?<![\d])(?:{_DAY}[./-]{_MONTH}[./-](?:\d{{4}}|\d{{2}})|\d{{4}}-{_MONTH}-{_DAY})(?![\d])"
)
YEAR_RANGE = re.compile(r"(?<![\d])(?:19|20)\d{2}\s?-\s?(?:19|20)\d{2}(?![\d])")

# "1 500 000", "1.500.000", "1500-2000" or "500 000 - 1 500 000": thousands
# grouping or a short range is an amount even without a currency word.
_FIGURE = r"(?:\d{1,3}(?:[ .]\d{3})+|\d{1,6})"
AMOUNT_SHAPED = re.compile(rf"{_FIGURE}(?:\s*-\s*{_FIGURE})?")

# How people lay out a card number: four groups of four with an optional
# tail, or one unbroken run. `patterns.CARD` accepts a single space or dash
# between digits; this also accepts double spaces, newlines and dots.
_CARD_GROUPS = r"\d{4}(?:[\s\-.]+\d{4}){3}(?:[\s\-.]+\d{1,3})?"
CARD_LAYOUT = re.compile(rf"(?:{_CARD_GROUPS}|\d{{16,19}})")
CARD_GROUPED = re.compile(rf"(?<![\d]){_CARD_GROUPS}(?![\d])")

# Detection runs over a probe copy of the text in which typographic dashes
# and non-breaking spaces are folded to ASCII. Every mapping is one character
# to one character, so a span found in the probe is the same span in the text.
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_SPACES = "\u00a0\u2009\u202f"
_PROBE_TABLE = str.maketrans(dict.fromkeys(_DASHES, "-") | dict.fromkeys(_SPACES, " "))


@dataclass(frozen=True)
class PiiSpan:
    label: str
    start: int
    end: int


@dataclass
class ScrubResult:
    text: str
    applied: list[str] = field(default_factory=list)


def mask_card(value: str) -> str:
    """Cards are replaced by their length alone.

    The presence of a card number matters to a scam verdict. Its value does
    not, and the safest field is an absent one.
    """
    return f"<CARD:{digit_count(value)}>"


def find_cards(text: str) -> list[str]:
    """Luhn-valid card numbers, returned already masked."""
    return [mask_card(m.group(0)) for m in CARD.finditer(text) if luhn(m.group(0))]


def find_iins(text: str) -> list[str]:
    """Kazakhstani individual identification numbers, returned masked."""
    return [PLACEHOLDER["iin"] for _ in IIN.finditer(text)]


def is_card_shaped(value: str) -> bool:
    """Luhn-valid at any length, or laid out as a card regardless.

    The Luhn test keeps order numbers out of the extractor's card set. For the
    scrubber a mistyped card is still a card, so anything written as four
    groups of four, or as an unbroken run of sixteen to nineteen digits, is
    masked even when the checksum fails.
    """
    return luhn(value) or CARD_LAYOUT.fullmatch(value) is not None


def is_amount_shaped(value: str) -> bool:
    return AMOUNT_SHAPED.fullmatch(value) is not None


def _is_loose_phone(value: str) -> bool:
    return is_phone_shaped(value) and not is_amount_shaped(value)


def _loose_phone_spans(value: str, offset: int) -> Iterator[tuple[str, int, int]]:
    """Judge one match of the loose phone pattern.

    A match with more digits than any telephone number is two numbers that
    only whitespace separates, so each whitespace-delimited part is judged on
    its own.
    """
    if digit_count(value) <= PHONE_MAX_DIGITS:
        if _is_loose_phone(value):
            yield ("phone", offset, offset + len(value))
        return
    for part in re.finditer(r"\S+", value):
        if is_card_shaped(part.group(0)):
            yield ("card", offset + part.start(), offset + part.end())
        elif _is_loose_phone(part.group(0)):
            yield ("phone", offset + part.start(), offset + part.end())


def _trim_punctuation(text: str, start: int, end: int) -> tuple[int, int]:
    """An email at the end of a sentence keeps its full stop."""
    while end > start and text[end - 1] in ".-":
        end -= 1
    return start, end


def find_pii(text: str) -> list[PiiSpan]:
    """Every span `scrub` would replace, in text order.

    Priority order matters, and it is the whole design:

    1. Emails, so a numeric local part is masked as part of the address.
    2. IBANs, whose account digits would otherwise read as a phone.
    3. Structured Kazakhstani and Chinese phone formats. These are claimed
       before amounts are reserved because "+7 707 123 45 67 500 тг" would
       otherwise reserve "67 500 тг" and let the phone survive.
    4. Amounts, dates and year ranges are reserved so a large tenge figure or
       a dotted date is never masked as a telephone number.
    5. Cards before the loose phone pattern, because a spaced fifteen-digit
       card satisfies both. Then identification numbers, loose phones, handles.

    The loose card pattern would also swallow a phone followed by a short
    code, which is why the structured phone formats come before it.
    """
    probe = text.translate(_PROBE_TABLE)
    claim = SpanClaim()
    found: list[PiiSpan] = []

    def take(label: str, start: int, end: int) -> None:
        if label == "email":
            start, end = _trim_punctuation(probe, start, end)
        if end > start and claim.claim(start, end):
            found.append(PiiSpan(label, start, end))

    def run(pattern: re.Pattern, label: str, guard: Callable[[str], bool] | None = None) -> None:
        for m in pattern.finditer(probe):
            if guard is None or guard(m.group(0)):
                take(label, m.start(), m.end())

    run(EMAIL, "email")
    run(IBAN, "iban")
    run(KZ_PHONE, "phone")
    run(CN_PHONE, "phone")
    for reserved in (AMOUNT_BEFORE_CURRENCY, AMOUNT_AFTER_CURRENCY, DATE, YEAR_RANGE):
        claim.reserve(reserved, probe)
    run(CARD_GROUPED, "card")
    run(CARD, "card", is_card_shaped)
    run(IIN, "iin")
    for m in PHONE.finditer(probe):
        for label, start, end in _loose_phone_spans(m.group(0), m.start()):
            take(label, start, end)
    run(HANDLE, "handle")

    found.sort(key=lambda s: s.start)
    return found


def scrub(text: str) -> ScrubResult:
    """Replace every PII class with a typed placeholder.

    Placeholders are typed rather than blanked so the text stays linguistically
    usable: a model can still learn that a message asked for *a card number*.
    `applied` lists the placeholder types used, sorted, without duplicates.
    """
    spans = find_pii(text)
    out = []
    cursor = 0
    for span in spans:
        out.append(text[cursor : span.start])
        out.append(PLACEHOLDER[span.label])
        cursor = span.end
    out.append(text[cursor:])
    return ScrubResult(text="".join(out), applied=sorted({s.label for s in spans}))


def contains_unmasked_pii(text: str) -> bool:
    """Assertion helper for tests and for the pre-write check on any row.

    True whenever `scrub` would still change the text, so the two can never
    disagree about what counts as personal data.
    """
    return bool(find_pii(text))
