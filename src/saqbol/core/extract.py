"""Stage 2: entity extraction.

Runs on the normalized text. Pure function, no network. Card numbers and
national identification numbers are masked at the moment of detection, so an
`Entities` object never holds either value.

Phone numbers are kept intact here because indicators I1 and I2 compare the
caller's country code against the institution it claims to be. They are masked
on the corpus path instead, by `privacy.scrub`, before any row is released.

Extraction is span-arbitrated. Patterns are offered in descending order of
specificity and the first to claim a region owns it, which is what stops a
national identification number from also being reported as a phone number and a
card number from also yielding four short codes. See `patterns.SpanClaim`.
"""

from __future__ import annotations

import tldextract

from saqbol.core.patterns import (
    AMOUNT_PREFIX,
    AMOUNT_SUFFIX,
    APK,
    BARE_DOMAIN,
    CARD,
    CRYPTO,
    IIN,
    PHONE,
    SCHEME_URL,
    SHORT_CODE,
    URL_TRAILING,
    WWW_URL,
    SpanClaim,
    is_phone_shaped,
    luhn,
)
from saqbol.core.privacy import PLACEHOLDER, mask_card
from saqbol.core.types import Entities

# Bundled public-suffix snapshot. An empty URL tuple keeps this offline, which
# the rules-only baseline and free CI both depend on.
_tld = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)

#: Remote-access tools, with the Cyrillic spellings a caller dictates by phone.
REMOTE_ACCESS_APPS: dict[str, tuple[str, ...]] = {
    "anydesk": ("anydesk", "any desk", "энидеск", "эни деск", "эникдеск"),
    "teamviewer": ("teamviewer", "team viewer", "тимвивер", "тим вивер"),
    "rustdesk": ("rustdesk", "растдеск", "раст деск"),
    "quicksupport": ("quicksupport", "quick support", "квиксаппорт"),
    "airdroid": ("airdroid", "эйрдроид"),
    "ammyy": ("ammyy", "амми админ", "ammyy admin"),
    "supremo": ("supremo", "супремо"),
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [i for i in items if not (i in seen or seen.add(i))]


def find_urls(text: str, claim: SpanClaim | None = None) -> list[str]:
    """URLs and bare domains, de-duplicated, in order of appearance."""
    claim = claim if claim is not None else SpanClaim()
    found: list[str] = []

    for pattern in (SCHEME_URL, WWW_URL):
        for m in pattern.finditer(text):
            if claim.claim(m.start(), m.end()):
                found.append(m.group(0).rstrip(URL_TRAILING))

    for m in BARE_DOMAIN.finditer(text):
        candidate = m.group(0).rstrip(URL_TRAILING)
        # A real public suffix is what separates "kaspi.kz" from the Russian
        # abbreviation "т.д." and from a filename like "document.apk".
        if not _tld(candidate).suffix:
            continue
        if claim.claim(m.start(), m.end()):
            found.append(candidate)

    return _dedupe(found)


def find_crypto(text: str, claim: SpanClaim | None = None) -> list[str]:
    claim = claim if claim is not None else SpanClaim()
    out: list[str] = []
    for pattern in CRYPTO:
        for m in pattern.finditer(text):
            if claim.claim(m.start(), m.end()):
                out.append(m.group(0))
    return _dedupe(out)


def find_cards(text: str, claim: SpanClaim | None = None) -> list[str]:
    """Luhn-valid card numbers, returned already masked."""
    claim = claim if claim is not None else SpanClaim()
    out: list[str] = []
    for m in CARD.finditer(text):
        if not luhn(m.group(0)):
            continue
        if claim.claim(m.start(), m.end()):
            out.append(mask_card(m.group(0)))
    return out


def find_iins(text: str, claim: SpanClaim | None = None) -> list[str]:
    claim = claim if claim is not None else SpanClaim()
    return [PLACEHOLDER["iin"] for m in IIN.finditer(text) if claim.claim(m.start(), m.end())]


def find_amounts(text: str, claim: SpanClaim | None = None) -> list[str]:
    claim = claim if claim is not None else SpanClaim()
    out: list[str] = []
    for pattern in (AMOUNT_SUFFIX, AMOUNT_PREFIX):
        for m in pattern.finditer(text):
            if claim.claim(m.start(), m.end()):
                out.append(m.group(0).strip())
    return _dedupe(out)


def find_phones(text: str, claim: SpanClaim | None = None) -> list[str]:
    claim = claim if claim is not None else SpanClaim()
    out: list[str] = []
    for m in PHONE.finditer(text):
        if not is_phone_shaped(m.group(0)):
            continue
        if claim.claim(m.start(), m.end()):
            out.append(m.group(0).strip())
    return _dedupe(out)


def find_short_codes(text: str, claim: SpanClaim | None = None) -> list[str]:
    """Standalone three to five digit numbers.

    Only reached for digit runs that no stronger pattern explained, so amounts,
    card groups and phone fragments never arrive here.
    """
    claim = claim if claim is not None else SpanClaim()
    if claim.free(0, len(text)):
        # Called standalone: reserve amounts so a tenge figure is not a code.
        claim.reserve(AMOUNT_SUFFIX, text)
        claim.reserve(AMOUNT_PREFIX, text)
    out: list[str] = []
    for m in SHORT_CODE.finditer(text):
        if claim.claim(m.start(), m.end()):
            out.append(m.group(1))
    return _dedupe(out)


def find_app_names(text: str) -> list[str]:
    lowered = text.casefold()
    return [
        canonical
        for canonical, spellings in REMOTE_ACCESS_APPS.items()
        if any(s in lowered for s in spellings)
    ]


def extract(text: str) -> Entities:
    """Stage 2 entrypoint.

    Claim order is the specificity order: links and wallet addresses, then
    checksummed identifiers, then money, then loose digit runs.
    """
    claim = SpanClaim()

    urls = find_urls(text, claim)
    crypto = find_crypto(text, claim)
    cards = find_cards(text, claim)
    iins = find_iins(text, claim)
    amounts = find_amounts(text, claim)
    phones = find_phones(text, claim)
    short_codes = find_short_codes(text, claim)

    return Entities(
        urls=urls,
        phones=phones,
        short_codes=short_codes,
        card_numbers=cards,
        iins=iins,
        amounts=amounts,
        crypto_addresses=crypto,
        app_names=find_app_names(text),
        has_apk=bool(APK.search(text)) or any(u.lower().endswith(".apk") for u in urls),
    )
