"""Stage 6 — the localized verdict card.

`render_card` is the only entry point the bot, the web app and the API use.
Everything they display comes from `src/saqbol/i18n/*.yaml` or from a playbook.
"""

from saqbol.render.card import Card, render_card
from saqbol.render.catalog import Catalog, Lookup, MissingString, catalog, load_tables

__all__ = [
    "Card",
    "Catalog",
    "Lookup",
    "MissingString",
    "catalog",
    "load_tables",
    "render_card",
]
