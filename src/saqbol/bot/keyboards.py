"""Inline keyboards.

Only the language picker for now. The verdict buttons — "was this right?",
"forward to family", "add to the dataset" — arrive with T204 and T206, which own
the persistence behind them.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from saqbol.bot.strings import LANGUAGE_NAMES, SUPPORTED_LOCALES
from saqbol.core.types import Lang

LANGUAGE_CALLBACK_PREFIX = "lang:"


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
