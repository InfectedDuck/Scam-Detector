"""Inline keyboards.

The language picker, and the three buttons under every verdict card: "was this
right?" as a yes/no pair, "forward to family", and "add to the dataset" (which
opens a confirm/cancel pair of its own). Every verdict button carries the check
id in its payload. That is the whole of the bot's per-card state: a vote or a
submission finds its row by that id, so it works after a restart and from a card
that is days old.

Telegram caps `callback_data` at 64 bytes. The longest payload built here is
`verdict:confirm:` plus a 32-character check id, 48 bytes. `CALLBACK_DATA_LIMIT`
is what a test holds every action against, so a longer prefix cannot be added
without noticing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from saqbol.bot.strings import LANGUAGE_NAMES, SUPPORTED_LOCALES, t
from saqbol.core.types import Lang

LANGUAGE_CALLBACK_PREFIX = "lang:"
VERDICT_CALLBACK_PREFIX = "verdict:"

#: Bot API limit on `callback_data`, in bytes.
CALLBACK_DATA_LIMIT = 64

#: A check id as it travels in a payload: `uuid.hex`, never the hyphenated form,
#: so the length is fixed and the parser can be strict.
_CHECK_ID_RE = re.compile(r"[0-9a-f]{32}")


class VerdictAction(StrEnum):
    """What a press under a card means. The value is the payload's middle part."""

    VOTE_YES = "yes"
    VOTE_NO = "no"
    SHARE = "share"
    DATASET_ASK = "add"
    DATASET_CONFIRM = "confirm"
    DATASET_CANCEL = "cancel"
    #: The inert button that replaces the vote pair once a vote is in.
    VOTED = "voted"


@dataclass(frozen=True)
class VerdictPress:
    action: VerdictAction
    check_id: str


# ---------------------------------------------------------------- language


def language_keyboard() -> InlineKeyboardMarkup:
    """Two by two, so all four fit without scrolling on a narrow phone."""
    buttons = [
        InlineKeyboardButton(
            text=LANGUAGE_NAMES[lang],
            callback_data=f"{LANGUAGE_CALLBACK_PREFIX}{lang.value}",
        )
        for lang in SUPPORTED_LOCALES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_language_callback(data: str | None) -> Lang | None:
    """Return the chosen locale, or `None` if the payload is not one of ours."""
    if not data or not data.startswith(LANGUAGE_CALLBACK_PREFIX):
        return None
    code = data[len(LANGUAGE_CALLBACK_PREFIX) :]
    try:
        lang = Lang(code)
    except ValueError:
        return None
    return lang if lang in SUPPORTED_LOCALES else None


# ----------------------------------------------------------------- verdict


def compact_check_id(check_id: str) -> str | None:
    """`check_id` as 32 lowercase hex characters, or `None` if it is not a UUID.

    The pipeline mints `uuid4().hex`, which is what the database keys rows by.
    Anything else cannot be voted on, so it gets no buttons rather than buttons
    that fail.
    """
    try:
        return uuid.UUID(str(check_id)).hex
    except ValueError:
        return None


def verdict_callback(action: VerdictAction, check_id: str) -> str:
    return f"{VERDICT_CALLBACK_PREFIX}{action.value}:{check_id}"


def parse_verdict_callback(data: str | None) -> VerdictPress | None:
    """Return the press, or `None` for anything that is not a well-formed payload."""
    if not data or not data.startswith(VERDICT_CALLBACK_PREFIX):
        return None
    action, sep, check_id = data[len(VERDICT_CALLBACK_PREFIX) :].partition(":")
    if not sep or _CHECK_ID_RE.fullmatch(check_id) is None:
        return None
    try:
        return VerdictPress(action=VerdictAction(action), check_id=check_id)
    except ValueError:
        return None


def _button(key: str, action: VerdictAction, check_id: str, locale: Lang) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=t(locale, key), callback_data=verdict_callback(action, check_id)
    )


def verdict_keyboard(check_id: str, locale: Lang, *, voted: bool = False) -> InlineKeyboardMarkup:
    """The three rows under a card. `check_id` must already be compact.

    With `voted`, the yes/no pair is replaced by one inert "thanks" button, which
    is how a card shows that its vote is in and cannot be cast again. The other
    two rows are unchanged, so the same markup serves the edit.
    """
    if voted:
        first = [_button("btn_voted", VerdictAction.VOTED, check_id, locale)]
    else:
        first = [
            _button("btn_vote_yes", VerdictAction.VOTE_YES, check_id, locale),
            _button("btn_vote_no", VerdictAction.VOTE_NO, check_id, locale),
        ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first,
            [_button("btn_share", VerdictAction.SHARE, check_id, locale)],
            [_button("btn_dataset", VerdictAction.DATASET_ASK, check_id, locale)],
        ]
    )


def dataset_confirm_keyboard(check_id: str, locale: Lang) -> InlineKeyboardMarkup:
    """Confirm and cancel, side by side, under the "what will be stored" text."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("btn_dataset_confirm", VerdictAction.DATASET_CONFIRM, check_id, locale),
                _button("btn_dataset_cancel", VerdictAction.DATASET_CANCEL, check_id, locale),
            ]
        ]
    )
