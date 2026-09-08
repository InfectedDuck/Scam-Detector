"""Turning a rendered `Card` into a Telegram message.

The renderer decides *what* a verdict says in the user's language. This module
only decides how it is laid out in a chat bubble, which is why it is here and
not in the renderer lane.

Sent as plain text with no `parse_mode`. Evidence quotes are fragments of an
attacker-supplied message, and every markup mode Telegram offers would either
break on them or let them inject formatting. Escaping is possible, but the
correct trade for a card that is mostly quoted hostile text is to not enter the
markup game at all.
"""

from __future__ import annotations

from saqbol.bot.deps import Card
from saqbol.bot.strings import t
from saqbol.core.types import Lang

#: Telegram rejects a message over 4096 characters.
TELEGRAM_MESSAGE_LIMIT = 4096

#: A single evidence quote longer than this is cut. The span is there to show
#: the reader which words triggered the verdict, not to replay the message.
MAX_QUOTE_CHARS = 200

ELLIPSIS = "…"


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + ELLIPSIS


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

    hotlines = [pair for pair in (card.hotlines or []) if pair]
    if hotlines:
        lines = [t(locale, "card_hotlines")]
        for pair in hotlines:
            label, number = (pair[0], pair[-1]) if len(pair) > 1 else (pair[0], pair[0])
            lines.append(f"• {number}" if label == number else f"• {label} — {number}")
        blocks.append("\n".join(lines))

    footer = (card.footer or "").strip()
    if footer:
        blocks.append(footer)

    text = "\n\n".join(blocks)
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[: TELEGRAM_MESSAGE_LIMIT - 1].rstrip() + ELLIPSIS
    return text
