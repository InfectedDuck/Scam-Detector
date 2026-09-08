"""Playbook schema.

Mirrors docs/02_DATA_CONTRACTS.md section 3. A playbook is the unit of domain
knowledge in this system: it names a scam script, supplies the phrases used to
retrieve it, and carries the advice shown to the user.

That last part is why validation here is strict rather than forgiving. The
model chooses which playbook applies; the playbook supplies what to do and who
to call, and those strings are never generated. A silently half-loaded playbook
would therefore show a victim incomplete advice, so every missing field is a
hard error at load time.

Russian is required and the other languages are optional, because the Kazakh
and Chinese translations arrive in week two. `Localized.missing()` reports the
gap so translation progress can be measured rather than guessed at.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from saqbol.core.types import Stage

#: The closed label set. Must match docs/04_PLAYBOOKS.md exactly; a test
#: asserts the two agree, the same way indicator ids are checked.
PLAYBOOK_IDS: tuple[str, ...] = (
    "kz.bank_security_call",
    "kz.egov_1414_code",
    "kz.delivery_link",
    "kz.marketplace_safe_deal",
    "kz.mule_account_rental",
    "kz.investment_deepfake",
    "kz.hijacked_account_relative",
    "kz.apk_install",
    "kz.fake_store",
    "kz.remote_access_loan",
    "cn.fake_police_deposit",
    "cn.currency_exchange",
    "cn.part_time_task_job",
)

#: Labels an annotator or the model may choose that are not playbooks.
#: `other_scam` is kept deliberately: without it annotators force-fit rows into
#: the nearest category and the corpus degrades.
FALLBACK_LABELS: tuple[str, ...] = ("none", "other_scam", "ambiguous")

LANGUAGES: tuple[str, ...] = ("ru", "kk", "en", "zh")
PRIMARY_LANGUAGE = "ru"

ID_PATTERN = re.compile(r"^(kz|cn)\.[a-z][a-z0-9_]*$")
URL_PATTERN = re.compile(r"^https?://\S+$")

MIN_RETRIEVAL_PHRASES = 5
MIN_RED_FLAGS = 2


class Localized(BaseModel):
    """One string per language. Russian is written first and is required."""

    model_config = ConfigDict(extra="forbid")

    ru: str = Field(min_length=1)
    kk: str | None = None
    en: str | None = None
    zh: str | None = None

    def get(self, lang: str) -> str:
        """The string for `lang`, falling back to Russian.

        Falling back is correct for a half-translated playbook: showing Russian
        advice to a Kazakh speaker is imperfect, showing nothing is worse.
        """
        return getattr(self, lang, None) or self.ru

    def missing(self) -> list[str]:
        return [lang for lang in LANGUAGES if not getattr(self, lang, None)]


class LocalizedList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ru: list[str] = Field(min_length=1)
    kk: list[str] | None = None
    en: list[str] | None = None
    zh: list[str] | None = None

    def get(self, lang: str) -> list[str]:
        return getattr(self, lang, None) or self.ru

    def missing(self) -> list[str]:
        return [lang for lang in LANGUAGES if not getattr(self, lang, None)]


class Hotline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    number: str = Field(min_length=2)


class Action(BaseModel):
    """What to do, plus the i18n key the renderer uses."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^action\.[a-z][a-z0-9_]*$")
    ru: str = Field(min_length=1)
    kk: str | None = None
    en: str | None = None
    zh: str | None = None

    def get(self, lang: str) -> str:
        return getattr(self, lang, None) or self.ru


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    region: Literal["KZ", "CN"]
    family: str = Field(min_length=1)

    name: Localized
    summary: Localized

    #: Embedded for retrieval, never displayed.
    retrieval_phrases: list[str] = Field(min_length=MIN_RETRIEVAL_PHRASES)
    #: Indicator ids that typically co-occur. Checked against the registry at
    #: load time, so a renamed rule cannot silently orphan a playbook.
    expected_indicators: list[str] = Field(default_factory=list)

    stages: dict[Stage, Localized] = Field(default_factory=dict)
    red_flags: LocalizedList

    action: Action
    hotline: str = Field(min_length=2)
    hotlines: list[Hotline] = Field(min_length=1)

    #: At least one official warning page. This is what separates a playbook
    #: from a blog post, and it is the first thing a datasheet reviewer checks.
    sources: list[str] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _known_id(cls, value: str) -> str:
        if not ID_PATTERN.match(value):
            raise ValueError(f"playbook id {value!r} must look like 'kz.bank_security_call'")
        if value not in PLAYBOOK_IDS:
            raise ValueError(
                f"playbook id {value!r} is not in the closed label set. "
                "Add it to PLAYBOOK_IDS and to docs/04_PLAYBOOKS.md first, "
                "since the set is also the dataset's label space."
            )
        return value

    @field_validator("sources")
    @classmethod
    def _real_urls(cls, values: list[str]) -> list[str]:
        for url in values:
            if not URL_PATTERN.match(url):
                raise ValueError(f"source {url!r} is not an http(s) URL")
        return values

    @field_validator("summary")
    @classmethod
    def _summary_fits_a_card(cls, value: Localized) -> Localized:
        for lang in LANGUAGES:
            text = getattr(value, lang, None)
            if text and len(text) > 200:
                raise ValueError(
                    f"summary.{lang} is {len(text)} characters; it is shown on the "
                    "verdict card and must stay under 200"
                )
        return value

    @model_validator(mode="after")
    def _enough_red_flags(self) -> Playbook:
        if len(self.red_flags.ru) < MIN_RED_FLAGS:
            raise ValueError(
                f"{self.id}: needs at least {MIN_RED_FLAGS} red flags. They are the "
                "educational payload and the reason someone forwards this to a parent."
            )
        return self

    @property
    def translation_gaps(self) -> dict[str, list[str]]:
        """Which languages each translatable field is still missing."""
        gaps = {
            "name": self.name.missing(),
            "summary": self.summary.missing(),
            "red_flags": self.red_flags.missing(),
            "action": [lang for lang in LANGUAGES if not getattr(self.action, lang, None)],
        }
        return {field: langs for field, langs in gaps.items() if langs}

    def embedding_text(self) -> str:
        """What gets embedded for retrieval: the summary plus the phrases."""
        return "\n".join([self.summary.ru, *self.retrieval_phrases])
