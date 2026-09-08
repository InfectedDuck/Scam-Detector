"""T114 — the localized verdict card.

Three things are worth testing here and the rest follows from them.

The first is that the four locale files declare the same keys. A missing Kazakh
string must fail the build, because the alternative is a raw key, or a silent
Russian sentence, reaching the person the tool was built for.

The second is that a card renders in every band and every locale without
reaching for a key that is not there. A `MissingString` in production is a blank
line in a warning someone is reading mid-scam.

The third is that an abstention still says something. A card with an empty body
is the one failure mode that looks like a working system.
"""

from __future__ import annotations

import pytest

import saqbol.core.indicators  # noqa: F401  — populates the registry
from saqbol.core.indicators.registry import REGISTRY
from saqbol.core.render import (
    LOCALES,
    MAX_EVIDENCE_LINES,
    PRIMARY,
    Card,
    MissingString,
    catalog,
    render_card,
)
from saqbol.core.types import (
    Band,
    Components,
    EvidenceSpan,
    IndicatorHit,
    Lang,
    Severity,
    Stage,
    Verdict,
)
from saqbol.playbooks.schema import Playbook

TRANSLATED = [lang for lang in LOCALES if lang is not PRIMARY]

#: An indicator whose Kazakh label is still `null  # TODO-kk`. If a translator
#: fills it in, `test_a_kazakh_gap_falls_back_and_says_so` will point here.
UNTRANSLATED_KK_INDICATOR = "G3.shortener"


def make_verdict(**overrides: object) -> Verdict:
    """A minimal scam verdict. Tests override the one field they care about."""
    fields: dict = {
        "check_id": "c0ffee01",
        "band": Band.SCAM,
        "risk": 0.91,
        "language": Lang.RU,
        "components": Components(rule_norm=0.9, retrieval_sim=0.7, llm_conf=0.9),
    }
    fields.update(overrides)
    return Verdict(**fields)


def span(text: str, indicator_id: str, start: int = 0) -> EvidenceSpan:
    return EvidenceSpan(start=start, end=start + len(text), text=text, indicator_id=indicator_id)


def make_playbook(**overrides: object) -> Playbook:
    """A valid playbook. Only Russian is filled in, which is the week-one state
    and exactly the case the fallback machinery exists for."""
    fields: dict = {
        "id": "kz.bank_security_call",
        "version": 1,
        "region": "KZ",
        "family": "authority_impersonation",
        "name": {"ru": "«Служба безопасности банка»"},
        "summary": {"ru": "Звонящий представляется сотрудником банка."},
        "retrieval_phrases": [
            "служба безопасности банка",
            "подозрительная операция по вашей карте",
            "назовите код из смс",
            "переведите на безопасный счёт",
            "не кладите трубку",
        ],
        "stages": {
            Stage.PRESSURE: {"ru": "Торопят и запрещают перезванивать."},
        },
        "red_flags": {"ru": ["Просят код из СМС.", "Торопят и пугают."]},
        "action": {
            "key": "action.hang_up_call_bank",
            "ru": "Положите трубку и позвоните в банк по номеру на обороте карты.",
        },
        "hotline": "1414",
        "hotlines": [{"name": "Банк, номер на карте", "number": "1414"}],
        "sources": ["https://www.gov.kz/memleket/entities/polisia"],
    }
    fields.update(overrides)
    return Playbook.model_validate(fields)


def strings(card: Card) -> list[str]:
    """Every user-visible string on a card, flattened."""
    parts = [card.title, card.band_label, card.summary, card.action, card.footer]
    parts.extend(card.evidence)
    parts.extend(line for line in (card.stage_now, card.stage_next) if line)
    parts.extend(name for name, _number in card.hotlines)
    return parts


# --------------------------------------------------------------------------
# The locale files


@pytest.mark.parametrize("lang", TRANSLATED, ids=lambda lang: lang.value)
def test_locale_files_declare_identical_keys(lang: Lang) -> None:
    """The point of the whole exercise.

    An untranslated string is declared with a `null` value, so the key set stays
    identical while the gap remains countable. A key that only exists in Russian
    would surface to a user as a raw key or as an unannounced Russian sentence.
    """
    primary = catalog().keys(PRIMARY)
    theirs = catalog().keys(lang)

    assert not primary - theirs, (
        f"{lang.value}.yaml is missing keys declared in {PRIMARY.value}.yaml: "
        f"{sorted(primary - theirs)}. Declare them with `null  # TODO-{lang.value}` "
        "rather than leaving them out."
    )
    assert not theirs - primary, (
        f"{lang.value}.yaml declares keys that {PRIMARY.value}.yaml does not: "
        f"{sorted(theirs - primary)}. Russian is the source language."
    )


def test_russian_is_complete() -> None:
    assert catalog().untranslated(PRIMARY) == []


def test_every_indicator_has_a_label() -> None:
    """A hit with no label is evidence the card cannot explain, and an orphan
    label is a rule that was renamed without the locale files following."""
    declared = catalog().keys()
    labelled = {key.split(".", 1)[1] for key in declared if key.startswith("indicator.")}
    assert not set(REGISTRY) - labelled, f"no label for {sorted(set(REGISTRY) - labelled)}"
    assert not labelled - set(REGISTRY), (
        f"labels for unknown rules {sorted(labelled - set(REGISTRY))}"
    )


def test_translation_progress_is_countable() -> None:
    """`untranslated` is what makes the Kazakh gap a number rather than a
    feeling. It may shrink to zero; it may not silently grow past the file."""
    for lang in TRANSLATED:
        assert set(catalog().untranslated(lang)) <= catalog().keys(PRIMARY)


def test_unknown_key_raises_and_is_not_a_key_error() -> None:
    """`MissingString` deliberately sits outside `KeyError`: a caller wrapping a
    render in `except KeyError` would otherwise ship a card with a hole in it."""
    with pytest.raises(MissingString):
        catalog().text("band.nonexistent.title", PRIMARY)
    assert not issubclass(MissingString, KeyError)


# --------------------------------------------------------------------------
# Rendering every band in every locale


@pytest.mark.parametrize("band", list(Band), ids=lambda band: band.value)
@pytest.mark.parametrize("locale", list(Lang), ids=lambda lang: lang.value)
def test_every_band_renders_in_every_locale(band: Band, locale: Lang) -> None:
    """No `MissingString`, and nothing important left blank.

    `Lang` is used deliberately rather than `LOCALES`: MIXED and UNKNOWN are
    properties of a message and do reach this function.
    """
    verdict = make_verdict(
        band=band,
        stage=Stage.PRESSURE,
        evidence=[span("код из смс", "A1.otp_request")],
    )
    card = render_card(verdict, locale)

    assert card.title
    assert card.band_label
    assert card.summary
    assert card.action
    assert card.footer
    assert card.evidence


def test_unrecognised_locale_renders_in_russian() -> None:
    """MIXED and UNKNOWN describe the text, not the reader. They are not a
    translation gap, so nothing is reported as a fallback."""
    for locale in (Lang.MIXED, Lang.UNKNOWN):
        card = render_card(make_verdict(), locale)
        assert card.locale is Lang.RU
        assert card.fallbacks == []


def test_no_raw_key_or_placeholder_reaches_a_card() -> None:
    """The failure this whole design exists to prevent."""
    verdict = make_verdict(
        stage=Stage.EXTRACTION,
        evidence=[span("срочно", "B1.urgency")],
        indicators=[
            IndicatorHit(indicator_id="I1.foreign_number_local_claim", severity=Severity.HIGH)
        ],
    )
    for locale in LOCALES:
        for text in strings(render_card(verdict, locale)):
            assert "{" not in text and "}" not in text, text
            assert not text.startswith(("band.", "indicator.", "action.", "stage.")), text


# --------------------------------------------------------------------------
# Abstention


@pytest.mark.parametrize("reason", ["disagreement", "low_self_consistency", "no_such_reason"])
def test_abstained_verdict_renders_the_unsure_card_with_its_reason(reason: str) -> None:
    """The requirement, stated directly: an abstention is shown as one, and the
    reason is in the body rather than only in the JSON."""
    verdict = make_verdict(
        band=Band.SCAM,
        abstained_because=reason,
        evidence=[span("код из смс", "A1.otp_request")],
    )
    card = render_card(verdict, Lang.RU)

    assert card.band_label == catalog().text("band.unsure.label", Lang.RU)[0]
    assert card.summary.strip()
    assert len(card.summary.splitlines()) == 2, "the reason line is missing from the body"
    assert card.evidence, "abstaining does not make the message unremarkable"

    expected_key = f"abstained.reason.{reason}"
    key = expected_key if catalog().has(expected_key) else "abstained.reason.unknown"
    assert catalog().text(key, Lang.RU)[0] in card.summary


def test_abstention_drops_the_playbook() -> None:
    """Fusion abstained because it does not know which script this is. Naming
    the script anyway, and handing over its advice, would claim more than the
    pipeline concluded."""
    verdict = make_verdict(
        playbook_id="kz.bank_security_call",
        abstained_because="disagreement",
    )
    card = render_card(verdict, Lang.RU, playbook=make_playbook())

    assert card.action_source == "generic"
    assert card.title == catalog().text("band.unsure.title", Lang.RU)[0]
    assert card.playbook_id == "kz.bank_security_call", "still recorded for telemetry"


# --------------------------------------------------------------------------
# Evidence


def test_evidence_quotes_the_message_and_names_the_rule() -> None:
    verdict = make_verdict(evidence=[span("безопасный счёт", "E1.safe_account")])
    line = render_card(verdict, Lang.RU).evidence[0]

    assert "безопасный счёт" in line
    assert catalog().text("indicator.E1.safe_account", Lang.RU)[0] in line


def test_metadata_indicators_appear_without_a_quote() -> None:
    """Family I has no spans; it reads the contact metadata. A foreign number
    behind a claimed Kazakhstani bank is often the clearest fact on the card."""
    verdict = make_verdict(
        indicators=[
            IndicatorHit(
                indicator_id="I1.foreign_number_local_claim",
                severity=Severity.HIGH,
                detail={"country_code": "+44"},
            )
        ]
    )
    card = render_card(verdict, Lang.RU)

    assert card.evidence == [catalog().text("indicator.I1.foreign_number_local_claim", Lang.RU)[0]]


def test_evidence_without_a_known_label_still_quotes_the_text() -> None:
    """A rule added ahead of its label degrades to the quote alone. Showing the
    reader a raw indicator id would be worse than showing them the phrase."""
    verdict = make_verdict(evidence=[span("что-то новое", "Z9.not_yet_named")])
    line = render_card(verdict, Lang.RU).evidence[0]

    assert "что-то новое" in line
    assert "Z9" not in line


def test_a_card_with_no_indicators_says_so() -> None:
    card = render_card(make_verdict(band=Band.LIKELY_SAFE), Lang.RU)
    assert card.evidence == [catalog().text("evidence.none", Lang.RU)[0]]


def test_evidence_is_capped_and_the_remainder_counted() -> None:
    ids = sorted(REGISTRY)[: MAX_EVIDENCE_LINES + 3]
    verdict = make_verdict(
        evidence=[span(f"фраза {n}", rule, start=n * 20) for n, rule in enumerate(ids)]
    )
    card = render_card(verdict, Lang.RU)

    assert len(card.evidence) == MAX_EVIDENCE_LINES + 1
    assert "3" in card.evidence[-1]


# --------------------------------------------------------------------------
# Advice comes from the playbook, never from a template


def test_playbook_supplies_the_action_and_the_hotlines() -> None:
    """The rule that matters most in this module. The model chooses the
    playbook; the playbook supplies what to do and who to call."""
    playbook = make_playbook()
    verdict = make_verdict(playbook_id=playbook.id, hotline="1414")
    card = render_card(verdict, Lang.RU, playbook=playbook)

    assert card.action == playbook.action.ru
    assert card.action_source == "playbook"
    assert card.hotlines == [("Банк, номер на карте", "1414")]
    assert card.title == playbook.name.ru
    assert card.summary == playbook.summary.ru
    assert card.action != catalog().text("action.generic.scam", Lang.RU)[0]


def test_playbook_describes_its_own_stage() -> None:
    playbook = make_playbook()
    verdict = make_verdict(playbook_id=playbook.id, stage=Stage.PRESSURE)
    card = render_card(verdict, Lang.RU, playbook=playbook)

    assert playbook.stages[Stage.PRESSURE].ru in card.stage_now
    # No description for the next stage, so the generic one carries it.
    assert catalog().text("stage.extraction.description", Lang.RU)[0] in card.stage_next


def test_a_playbook_id_with_no_file_yields_a_generic_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """Week one: retrieval names a playbook whose file has not landed. The card
    degrades to the per-band action rather than failing."""
    from saqbol.playbooks import loader

    monkeypatch.setattr(loader, "registry", dict)
    card = render_card(make_verdict(playbook_id="kz.fake_store"), Lang.RU)

    assert card.action_source == "generic"
    assert card.action == catalog().text("action.generic.scam", Lang.RU)[0]


def test_the_registry_is_consulted_when_no_playbook_is_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from saqbol.playbooks import loader

    playbook = make_playbook()
    monkeypatch.setattr(loader, "registry", lambda: {playbook.id: playbook})
    card = render_card(make_verdict(playbook_id=playbook.id), Lang.RU)

    assert card.action_source == "playbook"
    assert card.action == playbook.action.ru


def test_a_declared_action_key_is_preferred_to_the_band_default() -> None:
    """`Verdict.action_key` is an i18n key by contract. Most playbook keys are
    not declared here, since playbooks carry their own text, so the renderer
    uses one only when the locale files actually define it."""
    declared = render_card(make_verdict(action_key="action.generic.likely_safe"), Lang.RU)
    assert declared.action_source == "action_key"
    assert declared.action == catalog().text("action.generic.likely_safe", Lang.RU)[0]

    undeclared = render_card(make_verdict(action_key="action.hang_up_call_bank"), Lang.RU)
    assert undeclared.action_source == "generic"


# --------------------------------------------------------------------------
# Hotlines


def test_a_card_without_a_playbook_falls_back_to_the_national_hotlines() -> None:
    card = render_card(make_verdict(band=Band.SUSPICIOUS), Lang.RU)
    assert [number for _name, number in card.hotlines] == ["102", "1414"]
    assert all(name for name, _number in card.hotlines)


def test_the_verdict_hotline_leads_and_is_not_repeated() -> None:
    card = render_card(make_verdict(hotline="1414"), Lang.RU)
    assert [number for _name, number in card.hotlines] == ["1414", "102"]


def test_a_safe_looking_message_gets_no_hotline() -> None:
    """Telling someone to call the police about a message that looks fine trains
    them to ignore the card that matters."""
    assert render_card(make_verdict(band=Band.LIKELY_SAFE), Lang.RU).hotlines == []


# --------------------------------------------------------------------------
# Stages


def test_no_stage_means_no_stage_lines() -> None:
    card = render_card(make_verdict(stage=None), Lang.RU)
    assert card.stage_now is None
    assert card.stage_next is None


def test_the_last_stage_has_nothing_after_it() -> None:
    card = render_card(make_verdict(stage=Stage.CASHOUT), Lang.RU)
    assert card.stage_now
    assert card.stage_next is None


# --------------------------------------------------------------------------
# Fallback, and saying so


def test_a_kazakh_gap_falls_back_and_says_so() -> None:
    """A Russian sentence sitting silently in a Kazakh card is worse than an
    obvious one, so the fallback is both recorded and printed."""
    key = f"indicator.{UNTRANSLATED_KK_INDICATOR}"
    if catalog().text(key, Lang.KK)[0] != catalog().text(key, PRIMARY)[0]:
        pytest.skip(f"{key} has been translated; point this test at another TODO-kk key")

    verdict = make_verdict(evidence=[span("bit.ly/x", UNTRANSLATED_KK_INDICATOR)])
    card = render_card(verdict, Lang.KK)

    assert key in card.fallbacks
    assert catalog().text("footer.fallback", Lang.KK)[0] in card.footer


def test_a_fully_translated_card_admits_nothing() -> None:
    card = render_card(make_verdict(evidence=[span("код из смс", "A1.otp_request")]), Lang.KK)
    assert card.fallbacks == []
    assert catalog().text("footer.fallback", Lang.KK)[0] not in card.footer


def test_an_untranslated_playbook_is_reported_too() -> None:
    """The gap is not only in the locale files. A playbook written in Russian
    alone puts Russian advice in a Kazakh card, and the reader has to be told."""
    playbook = make_playbook()
    card = render_card(make_verdict(playbook_id=playbook.id), Lang.KK, playbook=playbook)

    assert card.action == playbook.action.ru
    assert "playbook.action" in card.fallbacks
    assert "playbook.summary" in card.fallbacks
    assert catalog().text("footer.fallback", Lang.KK)[0] in card.footer


def test_the_footer_carries_the_risk_and_the_check_id() -> None:
    card = render_card(make_verdict(check_id="abc123", risk=0.87), Lang.RU)
    assert "87" in card.footer
    assert "abc123" in card.footer
