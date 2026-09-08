"""Stage 6: a `Verdict` becomes a card someone can act on.

The renderer assembles; it never writes. Three rules hold the line:

1. **Every user-visible string comes from a locale file or from a playbook.**
   Nothing is inlined here, so a sentence can be corrected by someone who does
   not read Python.
2. **Action text and hotline numbers come from the playbook.** The model picks
   which playbook applies; it never authors what to do or who to call. A
   template that interpolated model output into advice would hand a scammer's
   own wording back to the victim as instructions.
3. **An abstention is shown as an abstention.** When fusion could not decide,
   the card drops the playbook rather than presenting a scenario the system
   does not stand behind, and says in the body why it is unsure. The evidence
   still shows: the spans are facts about the message and do not depend on the
   verdict.

When no playbook applies — the `rules_only` baseline, an unsure verdict, a
playbook id whose file has not landed yet — the card falls back to a per-band
action and to the national hotlines below. Those are curated constants, not
generated text, which is what keeps rule 2 intact.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from saqbol.core.types import Band, Lang, Stage, Verdict
from saqbol.playbooks.schema import Playbook
from saqbol.render.catalog import Lookup, catalog, resolve

#: The scam script in order. `stage_next` is the entry after the current one,
#: and this ordering is why the card can say what comes next.
STAGE_ORDER: tuple[Stage, ...] = (
    Stage.CONTACT,
    Stage.HOOK,
    Stage.TRUST,
    Stage.PRESSURE,
    Stage.EXTRACTION,
    Stage.CASHOUT,
)

#: Past this a card stops being read. The rest is summarised by `evidence.more`.
MAX_EVIDENCE_LINES = 6

#: Shown when no playbook supplies its own. The numbers live here rather than in
#: the locale files because a number is not a translation: four copies of "1414"
#: is four chances for one of them to be wrong, in the language least likely to
#: be proofread. The names beside them are keys, and those are translated.
DEFAULT_HOTLINE_NUMBERS: tuple[str, ...] = ("102", "1414")
HOTLINE_NAME_KEYS: dict[str, str] = {
    "102": "hotline.police",
    "1414": "hotline.egov",
    "110": "hotline.cn_police",
}

#: `likely_safe` gets no hotline. Telling someone to call the police about a
#: message that looks fine trains them to ignore the card that matters.
BANDS_WITH_HOTLINE: frozenset[Band] = frozenset({Band.SCAM, Band.SUSPICIOUS, Band.UNSURE})

ActionSource = Literal["playbook", "action_key", "generic"]


class Card(BaseModel):
    """What the bot, the web app and the API all render.

    The first nine fields are the seam every surface consumes. The rest is
    provenance: which playbook spoke, where the advice came from, and which
    strings the reader is seeing in the wrong language.
    """

    title: str
    band_label: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    stage_now: str | None = None
    stage_next: str | None = None
    action: str
    hotlines: list[tuple[str, str]] = Field(default_factory=list)
    footer: str

    locale: Lang = Lang.RU
    playbook_id: str | None = None
    action_source: ActionSource = "generic"
    #: i18n keys and playbook fields shown in Russian because the requested
    #: locale has no translation yet. Non-empty means the footer says so.
    fallbacks: list[str] = Field(default_factory=list)


def render_card(verdict: Verdict, locale: Lang, *, playbook: Playbook | None = None) -> Card:
    """The localized card for `verdict`.

    `playbook` is looked up from the registry by default; passing one keeps the
    renderer testable without playbook files on disk, and lets a caller that has
    already loaded the playbook avoid a second lookup.
    """
    lang = resolve(locale)
    text = Lookup(lang=lang, catalog=catalog())

    # An abstention is the system saying it does not know which script this is.
    # Presenting that script by name, with its advice, would be the one place a
    # card could claim more than the pipeline concluded.
    abstained = verdict.abstained_because
    band = Band.UNSURE if abstained else verdict.band
    book = None if abstained else (playbook or _playbook_for(verdict))

    if book is not None:
        title = _localized(book.name, text, "playbook.name")
        summary = _localized(book.summary, text, "playbook.summary")
    else:
        title = text(f"band.{band.value}.title")
        summary = text(f"band.{band.value}.summary")

    if abstained:
        summary = summary + "\n" + text("abstained.line", reason=_reason(abstained, text))

    action, action_source = _action(verdict, book, text)
    stage_now, stage_next = _stages(verdict, book, text)

    return Card(
        title=title,
        band_label=text(f"band.{band.value}.label"),
        summary=summary,
        evidence=_evidence(verdict, text),
        stage_now=stage_now,
        stage_next=stage_next,
        action=action,
        hotlines=_hotlines(verdict, book, band, text),
        footer=_footer(verdict, text),
        locale=lang,
        playbook_id=verdict.playbook_id,
        action_source=action_source,
        fallbacks=list(text.fallbacks),
    )


def _playbook_for(verdict: Verdict) -> Playbook | None:
    """The verdict's playbook, or None if it has none yet.

    `registry()` still raises on a malformed file — a half-loaded playbook must
    never reach a reader — but an id with no file yet is an ordinary week-one
    state and simply produces a generic card.
    """
    if not verdict.playbook_id:
        return None
    from saqbol.playbooks import loader  # local import keeps this module light

    return loader.registry().get(verdict.playbook_id)


def _localized(field: object, text: Lookup, label: str) -> str:
    """A playbook's own string in the requested language, Russian otherwise.

    `Localized.get` would fall back silently. Here the fallback has to end up
    visible on the card, so the attribute is read directly and recorded.
    """
    value = getattr(field, text.lang.value, None)
    if value:
        return value
    text.note(label)
    return getattr(field, Lang.RU.value)


def _reason(abstained_because: str, text: Lookup) -> str:
    """Why fusion declined to decide, in words.

    An unrecognised reason still says something, because an empty explanation is
    exactly what this card exists to avoid.
    """
    return text.optional(f"abstained.reason.{abstained_because}") or text(
        "abstained.reason.unknown"
    )


def _action(verdict: Verdict, book: Playbook | None, text: Lookup) -> tuple[str, ActionSource]:
    if book is not None:
        return _localized(book.action, text, "playbook.action"), "playbook"

    # `Verdict.action_key` is an i18n key by contract, but playbooks carry their
    # own action text, so most of those keys never appear here. Absence is
    # expected and is not an error.
    if verdict.action_key:
        from_key = text.optional(verdict.action_key)
        if from_key:
            return from_key, "action_key"

    return text(f"action.generic.{verdict.band.value}"), "generic"


def _stages(verdict: Verdict, book: Playbook | None, text: Lookup) -> tuple[str | None, str | None]:
    """Where the victim is, and what the script does next.

    Both are None for a single message: a stage is only meaningful once there is
    a thread to place it in, and inventing one would be the card's least
    defensible sentence.
    """
    stage = verdict.stage
    if stage is None:
        return None, None

    position = STAGE_ORDER.index(stage)
    following = STAGE_ORDER[position + 1] if position + 1 < len(STAGE_ORDER) else None
    return (
        _stage_line("stage.now", stage, book, text),
        _stage_line("stage.next", following, book, text) if following else None,
    )


def _stage_line(template: str, stage: Stage, book: Playbook | None, text: Lookup) -> str:
    """A playbook describes its own stages; the generic descriptions cover the
    case where none applies."""
    described: str | None = None
    if book is not None and stage in book.stages:
        described = _localized(book.stages[stage], text, f"playbook.stages.{stage.value}")
    return text(
        template,
        label=text(f"stage.{stage.value}.label"),
        description=described or text(f"stage.{stage.value}.description"),
    )


def _evidence(verdict: Verdict, text: Lookup) -> list[str]:
    """One line per quoted span, then the indicators that carry no span.

    Family I reads contact metadata rather than text, so it has a `detail` dict
    instead of a quote. Those hits still belong on the card: a foreign number
    behind a claimed Kazakhstani bank is often the clearest single fact in the
    whole message.
    """
    lines: list[str] = []

    for span in verdict.evidence:
        label = text.optional(f"indicator.{span.indicator_id}")
        line = (
            text("evidence.line", quote=span.text, label=label)
            if label
            else text("evidence.line_bare", quote=span.text)
        )
        if line not in lines:
            lines.append(line)

    spanless = sorted(
        (hit for hit in verdict.indicators if not hit.spans),
        key=lambda hit: -hit.weight,
    )
    for hit in spanless:
        label = text.optional(f"indicator.{hit.indicator_id}")
        if not label:
            continue
        line = text("evidence.line_no_quote", label=label)
        if line not in lines:
            lines.append(line)

    if not lines:
        return [text("evidence.none")]
    if len(lines) > MAX_EVIDENCE_LINES:
        hidden = len(lines) - MAX_EVIDENCE_LINES
        return [*lines[:MAX_EVIDENCE_LINES], text("evidence.more", count=hidden)]
    return lines


def _hotlines(
    verdict: Verdict, book: Playbook | None, band: Band, text: Lookup
) -> list[tuple[str, str]]:
    if book is not None:
        return [(entry.name, entry.number) for entry in book.hotlines]

    numbers = [verdict.hotline] if verdict.hotline else []
    if band in BANDS_WITH_HOTLINE:
        numbers.extend(DEFAULT_HOTLINE_NUMBERS)

    listed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number in numbers:
        if number in seen:
            continue
        seen.add(number)
        listed.append((text(HOTLINE_NAME_KEYS.get(number, "hotline.generic")), number))
    return listed


def _footer(verdict: Verdict, text: Lookup) -> str:
    """Built last, because the fallback notice can only be written once every
    other string has been looked up."""
    lines = [
        text("footer.disclaimer"),
        text("footer.risk", percent=round(verdict.risk * 100)),
        text("footer.check_id", check_id=verdict.check_id),
    ]
    if text.fallbacks:
        lines.append(text("footer.fallback"))
    return "\n".join(lines)
