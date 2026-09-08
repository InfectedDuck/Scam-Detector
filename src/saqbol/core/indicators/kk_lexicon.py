"""Kazakh phrase lists, loaded from ``core/data/kk_lexicon.yaml``.

Every Kazakh pattern in the catalogue lives in that YAML file and nowhere else,
so the week-3 native-speaker review is one file to read rather than seven Python
modules. This module is only the seam between the two: family modules call
``kk("A1.otp_request")`` where they used to hold a `# TODO-kk` list.

Loading is eager rather than lazy, deliberately. The lists are consumed at
import time by `keyword_indicator`, so a malformed file or a mistyped indicator
id fails when the package is imported, not silently at the first message that
needed the rule.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

LEXICON = Path(__file__).resolve().parent.parent / "data" / "kk_lexicon.yaml"


@lru_cache(maxsize=1)
def load() -> dict[str, tuple[str, ...]]:
    """Parse the lexicon into ``{indicator_id: phrases}``."""
    raw = yaml.safe_load(LEXICON.read_text(encoding="utf-8")) or {}
    phrases = raw.get("phrases") or {}
    if not isinstance(phrases, dict):
        raise ValueError(f"{LEXICON.name}: 'phrases' must be a mapping of indicator id to list")
    out: dict[str, tuple[str, ...]] = {}
    for indicator_id, entries in phrases.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{LEXICON.name}: {indicator_id} must carry a non-empty list")
        out[indicator_id] = tuple(str(e).strip() for e in entries)
    return out


def kk(indicator_id: str) -> tuple[str, ...]:
    """Kazakh phrases for one indicator.

    Raises rather than returning empty: an indicator asking for a list that the
    lexicon does not carry is a typo, and a silent empty list would restore the
    exact hole the `TODO-kk` markers stood for.
    """
    try:
        return load()[indicator_id]
    except KeyError:
        raise KeyError(
            f"{indicator_id} has no entry in {LEXICON.name}. "
            "Kazakh phrases belong in that file, not in the family module."
        ) from None
