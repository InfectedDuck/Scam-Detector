"""Stage 0: normalization, script analysis and language identification.

Every downstream character offset refers to `NormalizedText.text`, never to the
raw input. NFKC changes string length, so the two are not interchangeable.

No dependencies beyond the standard library and `regex`.
"""

from __future__ import annotations

import unicodedata

import regex as re

from saqbol.core.types import Lang, NormalizedText

# Zero-width, bidirectional controls and the soft hyphen. All are invisible and
# all are used to break naive keyword matching.
INVISIBLE = re.compile(
    "["
    "­"  # soft hyphen
    "​-‏"  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "‪-‮"  # bidi embedding / override
    "⁠-⁤"  # word joiner, invisible operators
    "⁪-⁯"
    "﻿"  # BOM / ZWNBSP
    "]"
)

_HORIZONTAL_WS = re.compile(r"[^\S\n]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_TOKEN = re.compile(r"\p{L}[\p{L}\p{M}\p{Nd}]*")

# The nine letters in the Kazakh Cyrillic alphabet that Russian does not use.
# Russian has no letters that Kazakh lacks, so detection can only run this way.
KAZAKH_SPECIFIC = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")

#: Share of Cyrillic tokens carrying a Kazakh-specific letter, above which the
#: message is treated as Kazakh rather than as code-switched Russian.
KAZAKH_TOKEN_THRESHOLD = 0.15


def _script_of(ch: str) -> str:
    """Coarse script bucket for a single character. Letters only."""
    cp = ord(ch)
    if 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F:
        return "cyrillic"
    if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
        return "latin"
    if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF:
        return "han"
    if 0x3040 <= cp <= 0x30FF:
        return "kana"
    if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:
        return "arabic"
    return "other"


def strip_invisible(text: str) -> str:
    return INVISIBLE.sub("", text)


def collapse_whitespace(text: str) -> str:
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _MANY_NEWLINES.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def script_ratios(text: str) -> dict[str, float]:
    """Share of each script among letter characters. Empty dict if no letters."""
    counts: dict[str, int] = {}
    total = 0
    for ch in text:
        if not ch.isalpha():
            continue
        counts[_script_of(ch)] = counts.get(_script_of(ch), 0) + 1
        total += 1
    if total == 0:
        return {}
    return {k: v / total for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}


def mixed_script_tokens(text: str) -> list[str]:
    """Tokens containing more than one script.

    A Latin word carrying a single Cyrillic lookalike is the classic homograph
    attack on brand names, for example "kaspі.kz" with Cyrillic i.
    """
    out = []
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        scripts = {_script_of(c) for c in token if c.isalpha()}
        scripts.discard("other")
        if len(scripts) > 1:
            out.append(token)
    return out


def _kazakh_word_ratio(text: str) -> float:
    """Share of Cyrillic tokens containing at least one Kazakh-specific letter."""
    cyrillic_tokens = 0
    kazakh_tokens = 0
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if not any(_script_of(c) == "cyrillic" for c in token if c.isalpha()):
            continue
        cyrillic_tokens += 1
        if any(c in KAZAKH_SPECIFIC for c in token):
            kazakh_tokens += 1
    if cyrillic_tokens == 0:
        return 0.0
    return kazakh_tokens / cyrillic_tokens


def detect_language(text: str) -> tuple[Lang, float, bool]:
    """Return (language, confidence, is_code_switched).

    Deliberately a transparent heuristic rather than a model. It has to run on
    CPU in microseconds inside the rules-only baseline, and its failure modes
    need to be explainable in a paper.
    """
    # URLs are Latin regardless of the message language and would otherwise
    # make every Russian message with a link look code-switched.
    for_langid = _URL.sub(" ", text)
    ratios = script_ratios(for_langid)
    if not ratios:
        return Lang.UNKNOWN, 0.0, False

    cyr = ratios.get("cyrillic", 0.0)
    lat = ratios.get("latin", 0.0)
    han = ratios.get("han", 0.0) + ratios.get("kana", 0.0)

    kk_ratio = _kazakh_word_ratio(for_langid)

    # Two scripts each holding a real share, or Kazakh and Russian tokens mixed
    # inside one Cyrillic message.
    top_two = sorted(ratios.values(), reverse=True)[:2]
    script_mixed = len(top_two) == 2 and top_two[1] >= 0.15
    cyrillic_mixed = cyr >= 0.5 and 0.05 <= kk_ratio <= 0.70
    code_switched = script_mixed or cyrillic_mixed

    if han >= max(cyr, lat) and han > 0:
        return Lang.ZH, min(1.0, han + 0.2), code_switched

    if cyr >= lat and cyr > 0:
        # Kazakh uses these letters densely, so genuine Kazakh text sits far
        # above this threshold. Below it we are looking at Russian carrying a
        # Kazakh greeting or a single borrowed word, which is Russian that is
        # also code-switched, not Kazakh.
        if kk_ratio >= KAZAKH_TOKEN_THRESHOLD:
            return Lang.KK, min(1.0, 0.55 + kk_ratio), code_switched
        if kk_ratio > 0:
            return Lang.RU, min(1.0, 0.5 + cyr / 2), True
        return Lang.RU, min(1.0, 0.5 + cyr / 2), code_switched

    if lat > 0:
        return Lang.EN, min(1.0, 0.4 + lat / 2), code_switched

    return Lang.UNKNOWN, 0.0, code_switched


def normalize(raw: str, lang_hint: Lang | None = None) -> NormalizedText:
    """Stage 0 entrypoint.

    Order matters: invisibles are removed before NFKC, because NFKC does not
    remove them and they would survive into the matched text.
    """
    stripped = strip_invisible(raw)
    composed = unicodedata.normalize("NFKC", stripped)
    text = collapse_whitespace(composed)

    lang, confidence, code_switched = detect_language(text)
    if lang_hint is not None and lang is Lang.UNKNOWN:
        lang, confidence = lang_hint, 0.3

    return NormalizedText(
        text=text,
        original=raw,
        lang=lang,
        lang_confidence=round(confidence, 3),
        is_code_switched=code_switched,
        script_ratios={k: round(v, 3) for k, v in script_ratios(text).items()},
        mixed_script_tokens=mixed_script_tokens(text),
    )
