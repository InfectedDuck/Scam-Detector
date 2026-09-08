"""Turning a rendered `Card` into a Telegram message.

The renderer decides *what* a verdict says in the user's language. This module
only decides how it is laid out in a chat bubble, which is why it is here and
not in the renderer.

Sent as plain text with no `parse_mode`. Evidence quotes are fragments of an
attacker-supplied message, and every markup mode Telegram offers would either
break on them or let them inject formatting. Escaping is possible, but the
correct trade for a card that is mostly quoted hostile text is to not enter the
markup game at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from saqbol.bot.deps import Card, RenderCard
from saqbol.bot.strings import t
from saqbol.core.types import Lang, Verdict

#: Telegram rejects a message over 4096 characters.
TELEGRAM_MESSAGE_LIMIT = 4096

#: A single evidence quote longer than this is cut. The span is there to show
#: the reader which words triggered the verdict, not to replay the message.
MAX_QUOTE_CHARS = 200

ELLIPSIS = "…"

#: The share text opens in both of these, whatever the reader chose: the person
#: it is forwarded to has chosen nothing. Same reasoning as the consent block.
SHARE_WARNING_LANGUAGES = (Lang.RU, Lang.KK)


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + ELLIPSIS


def _hotline_entries(hotlines: Sequence[tuple[str, str]] | None) -> list[str]:
    """`"102"` when the label is the number, `"label — number"` otherwise."""
    entries = []
    for pair in hotlines or []:
        if not pair:
            continue
        label, number = (pair[0], pair[-1]) if len(pair) > 1 else (pair[0], pair[0])
        entries.append(number if label == number else f"{label} — {number}")
    return entries


def format_card(card: Card, locale: Lang, *, notice: str | None = None) -> str:
    """Lay a card out as one plain-text message."""
    blocks: list[str] = []

    if notice:
        blocks.append(notice)

    heading = card.title.strip()
    if heading:
        blocks.append(heading)

    summary = (card.summary or "").strip()
    if summary:
        blocks.append(summary)

    quotes = [_clip(q, MAX_QUOTE_CHARS) for q in (card.evidence or []) if q and q.strip()]
    if quotes:
        lines = [t(locale, "card_evidence")]
        lines += [f"• «{quote}»" for quote in quotes]
        blocks.append("\n".join(lines))

    stage_lines = []
    if card.stage_now:
        stage_lines.append(f"{t(locale, 'card_stage')} {card.stage_now}")
    if card.stage_next:
        stage_lines.append(f"{t(locale, 'card_stage_next')} {card.stage_next}")
    if stage_lines:
        blocks.append("\n".join(stage_lines))

    action = (card.action or "").strip()
    if action:
        blocks.append(f"{t(locale, 'card_action')}\n{action}")

    hotlines = _hotline_entries(card.hotlines)
    if hotlines:
        lines = [t(locale, "card_hotlines")]
        lines += [f"• {entry}" for entry in hotlines]
        blocks.append("\n".join(lines))

    footer = (card.footer or "").strip()
    if footer:
        blocks.append(footer)

    text = "\n\n".join(blocks)
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[: TELEGRAM_MESSAGE_LIMIT - 1].rstrip() + ELLIPSIS
    return text


def share_text(verdict: Verdict, locale: Lang, render_card: RenderCard) -> str:
    """The message a reader forwards to family. Nothing of the reader is in it.

    It is built from the renderer's own labels — the band, the playbook's name
    when one applies, the hotlines — and never from the evidence or the summary,
    because those quote the message the reader sent. No identifier of any kind
    goes in either: the text is meant to leave the chat.

    The safety line comes first and in both languages, since it is the part
    that still helps if the recipient reads nothing else. The verdict lines
    follow in the reader's own language.
    """
    card = render_card(verdict, locale)
    warning = "\n".join(t(lang, "share_warning") for lang in SHARE_WARNING_LANGUAGES)

    band = card.band_label.strip() or verdict.band.value
    lines = [t(locale, "share_verdict", band=band)]

    # The renderer titles a card with the playbook's name when one applies, and
    # with a band title otherwise (including when the pipeline abstained), so
    # the title is only a playbook name under the same condition.
    name = card.title.strip()
    if verdict.playbook_id and not verdict.abstained_because and name:
        lines.append(t(locale, "share_playbook", name=_clip(name, MAX_QUOTE_CHARS)))

    hotlines = ", ".join(_hotline_entries(card.hotlines)) or verdict.hotline.strip()
    if hotlines:
        lines.append(t(locale, "share_hotline", hotlines=hotlines))

    return f"{warning}\n\n" + "\n".join(lines)
