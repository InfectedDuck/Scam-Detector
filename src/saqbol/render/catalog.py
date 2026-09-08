"""The four locale files, loaded once, with one explicit fallback rule.

Every user-visible string in SaqBol lives in `src/saqbol/i18n/{ru,kk,en,zh}.yaml`
and nothing else. Code holds keys; the files hold prose. That is what lets a
Kazakh speaker fix a Kazakh sentence without reading Python, and what lets a
test prove the four files still agree.

Two rules, and the reasons they are worth the machinery:

* **Russian is complete or the build fails.** Russian is the language every
  playbook is written in first, so a missing Russian string is a bug in this
  package rather than a translation gap. `load_tables` refuses to return a
  table with a hole in it.
* **A missing Kazakh or Chinese string falls back to Russian, and the fallback
  is recorded.** A Russian sentence sitting silently inside a Kazakh card is
  worse than an obviously untranslated one: the reader cannot tell whether the
  tool is half-built or whether the advice itself was meant for someone else.
  `Lookup` therefore collects every key it had to fall back on, and the card
  says so in its footer.

An untranslated string is written as an explicit `null` with a `# TODO-kk`
comment rather than being left out. The key still exists, so the identical-key
test keeps passing while `untranslated()` can count the real gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from saqbol.core.types import Lang

I18N_DIR = Path(__file__).resolve().parents[1] / "i18n"

#: The locales that have a file. `Lang` also has MIXED and UNKNOWN, which are
#: properties of a message rather than choices a reader makes; both resolve to
#: the primary locale.
LOCALES: tuple[Lang, ...] = (Lang.RU, Lang.KK, Lang.EN, Lang.ZH)
PRIMARY: Lang = Lang.RU


class MissingString(LookupError):
    """A key absent from the primary locale, or a broken placeholder.

    Deliberately not a `KeyError`: callers that catch `KeyError` around a render
    would otherwise swallow it and ship a card with a hole in it.
    """


def flatten(node: object, prefix: str = "") -> dict[str, str | None]:
    """Nested YAML to dotted keys.

    The files nest for readability; the code addresses one flat namespace, so
    `indicator: {A1.otp_request: ...}` is reached as `indicator.A1.otp_request`.
    """
    flat: dict[str, str | None] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            flat.update(flatten(value, f"{prefix}{key}."))
        return flat
    if node is None or isinstance(node, str):
        flat[prefix.rstrip(".")] = node
        return flat
    raise MissingString(
        f"{prefix.rstrip('.')!r} is a {type(node).__name__}. Locale files hold "
        "strings and nested mappings only; a list here means a card would be "
        "assembled by the file rather than by the renderer."
    )


def _read(lang: Lang) -> dict[str, str | None]:
    path = I18N_DIR / f"{lang.value}.yaml"
    if not path.is_file():
        raise MissingString(f"no locale file at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MissingString(f"{path.name}: expected a mapping at the top level")
    return flatten(raw)


@lru_cache(maxsize=1)
def load_tables() -> dict[Lang, dict[str, str | None]]:
    """Every locale file, flattened. Cached; call `load_tables.cache_clear()`
    after editing a file in a test."""
    tables = {lang: _read(lang) for lang in LOCALES}

    holes = sorted(key for key, value in tables[PRIMARY].items() if not value)
    if holes:
        raise MissingString(
            f"{PRIMARY.value}.yaml has {len(holes)} empty values: {holes[:5]}. "
            "Russian is the source language, so an empty value here is a "
            "missing string rather than a pending translation."
        )
    return tables


class Catalog:
    """Read-only access to the loaded tables."""

    def __init__(self, tables: dict[Lang, dict[str, str | None]]) -> None:
        self._tables = tables

    @property
    def languages(self) -> tuple[Lang, ...]:
        return LOCALES

    def keys(self, lang: Lang = PRIMARY) -> set[str]:
        """Every declared key, including the ones whose value is still null."""
        return set(self._tables[lang])

    def has(self, key: str) -> bool:
        return key in self._tables[PRIMARY]

    def untranslated(self, lang: Lang) -> list[str]:
        """Keys still waiting on a translator. The `# TODO-kk` count, countable."""
        if lang is PRIMARY:
            return []
        table = self._tables[lang]
        return sorted(key for key in self._tables[PRIMARY] if not table.get(key))

    def text(self, key: str, lang: Lang, **values: object) -> tuple[str, bool]:
        """`(text, fell_back_to_russian)` for `key`."""
        primary = self._tables[PRIMARY].get(key)
        if primary is None:
            raise MissingString(
                f"no string for {key!r} in {PRIMARY.value}.yaml. Every user-visible "
                "string lives in the locale files, so this is a missing entry, not "
                "a reason to inline one."
            )

        chosen, fell_back = primary, False
        if lang is not PRIMARY:
            translated = self._tables.get(lang, {}).get(key)
            if translated:
                chosen = translated
            else:
                fell_back = True

        return _format(key, chosen, values), fell_back


def _format(key: str, template: str, values: dict[str, object]) -> str:
    if not values:
        return template
    try:
        return template.format(**values)
    except (KeyError, IndexError) as err:
        raise MissingString(
            f"{key!r} uses a placeholder the renderer does not supply ({err}). "
            "Placeholders are part of the contract between the code and the "
            "translators; changing one in a locale file breaks the card."
        ) from err


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    return Catalog(load_tables())


def resolve(locale: Lang) -> Lang:
    """The locale to render in. MIXED and UNKNOWN describe the message, not the
    reader, so they get the primary locale."""
    return locale if locale in LOCALES else PRIMARY


@dataclass
class Lookup:
    """A locale-bound view of the catalogue that remembers what it fell back on.

    The renderer holds one of these for the length of a card, so the finished
    card can name every string the reader is seeing in the wrong language.
    """

    lang: Lang
    catalog: Catalog
    fallbacks: list[str] = field(default_factory=list)

    def __call__(self, key: str, **values: object) -> str:
        text, fell_back = self.catalog.text(key, self.lang, **values)
        if fell_back:
            self.note(key)
        return text

    def optional(self, key: str, **values: object) -> str | None:
        """The string for `key`, or None if no such key is declared.

        Used for keys supplied from outside this package, such as a playbook's
        `action_key`, where absence is a fact rather than a bug.
        """
        return self(key, **values) if self.catalog.has(key) else None

    def note(self, label: str) -> None:
        """Record a fallback for something not addressed by an i18n key, such as
        a playbook field whose Kazakh translation has not landed yet."""
        if label not in self.fallbacks:
            self.fallbacks.append(label)
