"""SaqBol Telegram bot.

Entry point: `python -m saqbol.bot.main`.

`deps.py` holds the seam to the analysis pipeline and the card renderer. Nothing
else in this package imports either, so both can land later without touching a
handler.
"""

from saqbol.bot.config import BotConfig
from saqbol.bot.deps import Analyze, Card, Deps, RenderCard, build_deps
from saqbol.bot.storage import BotStore

__all__ = [
    "Analyze",
    "BotConfig",
    "BotStore",
    "Card",
    "Deps",
    "RenderCard",
    "build_deps",
]
