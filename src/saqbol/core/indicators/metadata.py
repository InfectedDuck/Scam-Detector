"""Family I — contact metadata anomalies.

These rules compare what the message *claims* against what the channel
*shows*. Pasted text carries none of that, so every rule here returns nothing
when the surface supplied no metadata. Guessing from the text would manufacture
signal that is not there, and it would corrupt the combination bonus that pairs
a claimed institution with a contradicting contact.

Metadata keys, supplied by the Telegram handler in T202:

    sender_phone        str   the number the message actually came from
    claimed_number      str   a number the message says it is from
    account_age_days    int   age of the sending account
    has_username        bool
    is_known_contact    bool
"""

from __future__ import annotations

from saqbol.core.indicators.registry import DetectionContext, find_phrase_spans, indicator
from saqbol.core.types import IndicatorHit, Severity

#: Institutions whose calls should originate inside Kazakhstan.
KZ_INSTITUTION_PHRASES = (
    "kaspi",
    "каспи",
    "халык",
    "halyk",
    "жусан",
    "jusan",
    "forte",
    "форте",
    "freedom",
    "фридом",
    "otbasy",
    "отбасы",
    "казпочта",
    "kazpost",
    "егов",
    "egov",
    "нацбанк",
    "национальн* банк*",
    "служба безопасности банка",
)

KZ_COUNTRY_CODE = "7"


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


@indicator(
    "I1.foreign_number_local_claim",
    Severity.HIGH,
    "A number outside Kazakhstan while claiming a Kazakhstani institution",
)
def foreign_number_local_claim(ctx: DetectionContext) -> list[IndicatorHit]:
    """Text-detectable, unlike the rest of the family.

    The claim is in the message body and the number is in the message body, so
    the contradiction can be seen without any channel metadata.
    """
    claim_spans = find_phrase_spans(ctx, KZ_INSTITUTION_PHRASES, "I1.foreign_number_local_claim")
    if not claim_spans:
        return []

    foreign = []
    for phone in ctx.entities.phones:
        if not phone.strip().startswith("+"):
            # Without a leading plus the country code is unknowable. A bare
            # eleven-digit local number is the normal case, not a signal.
            continue
        digits = _digits(phone)
        if digits and not digits.startswith(KZ_COUNTRY_CODE):
            foreign.append(phone)

    if not foreign:
        return []
    return [
        IndicatorHit(
            indicator_id="I1.foreign_number_local_claim",
            severity=Severity.HIGH,
            spans=claim_spans,
            detail={"foreign_numbers": foreign},
        )
    ]


@indicator(
    "I2.spoofed_short_code",
    Severity.HIGH,
    "A long number presented as an institutional short code",
)
def spoofed_short_code(ctx: DetectionContext) -> list[IndicatorHit]:
    claimed = ctx.metadata.get("claimed_number")
    sender = ctx.metadata.get("sender_phone")
    if not claimed or not sender:
        return []
    if len(_digits(claimed)) <= 5 < len(_digits(sender)):
        return [
            IndicatorHit(
                indicator_id="I2.spoofed_short_code",
                severity=Severity.HIGH,
                detail={"claimed": claimed, "actual_length": len(_digits(sender))},
            )
        ]
    return []


@indicator(
    "I3.new_telegram_account",
    Severity.MEDIUM,
    "Message forwarded from a newly created or anonymous account",
)
def new_telegram_account(ctx: DetectionContext) -> list[IndicatorHit]:
    age = ctx.metadata.get("account_age_days")
    has_username = ctx.metadata.get("has_username")
    if age is None and has_username is None:
        return []
    suspicious = (age is not None and age < 30) or has_username is False
    if not suspicious:
        return []
    return [
        IndicatorHit(
            indicator_id="I3.new_telegram_account",
            severity=Severity.MEDIUM,
            detail={"account_age_days": age, "has_username": has_username},
        )
    ]


@indicator(
    "I4.relative_new_number",
    Severity.MEDIUM,
    "Claims to be a relative while writing from an unknown contact",
)
def relative_new_number(ctx: DetectionContext) -> list[IndicatorHit]:
    if ctx.metadata.get("is_known_contact") is not False:
        return []
    spans = find_phrase_spans(
        ctx,
        [
            "это мама",
            "это папа",
            "это твой сын",
            "это твоя дочь",
            "это я твой",
            "мам это я",
            "пап это я",
            "it's your son",
            "it's your daughter",
        ],
        "I4.relative_new_number",
    )
    if not spans:
        return []
    return [
        IndicatorHit(
            indicator_id="I4.relative_new_number",
            severity=Severity.MEDIUM,
            spans=spans,
        )
    ]
