"""Bodies that exist only on the wire.

The domain types (`AnalysisInput`, `Verdict`) come from `saqbol.core.types`
unchanged. This module adds what the HTTP surface needs on top of them and
defines the public projection of a playbook.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from saqbol.core.types import Verdict
from saqbol.playbooks.schema import Hotline, Localized, LocalizedList, Playbook


class AnalyzeOut(Verdict):
    """A verdict plus the text its evidence offsets index into.

    Spans point into the normalized text, not into what the client sent, so a
    client holding only the verdict cannot draw a highlight without
    re-implementing the normalizer. Sending the normalized text makes the
    offsets usable exactly as they are.
    """

    normalized_text: str

    @classmethod
    def from_verdict(cls, verdict: Verdict, normalized_text: str) -> AnalyzeOut:
        return cls.model_validate({**verdict.model_dump(), "normalized_text": normalized_text})


class FeedbackIn(BaseModel):
    """POST /api/v1/feedback. `was_correct` may be null for "not sure"."""

    check_id: str = Field(min_length=1, max_length=64)
    was_correct: bool | None = None
    comment: str | None = Field(default=None, max_length=2000)


class HealthOut(BaseModel):
    ok: bool
    db: bool
    llm: bool


class ActionOut(BaseModel):
    #: The i18n key a verdict's `action_key` refers to.
    key: str
    #: Language code -> advice, for the languages that have a translation.
    text: dict[str, str]


def _present(localized: Localized | LocalizedList) -> dict:
    """Only the languages that exist; Russian is always among them."""
    return localized.model_dump(exclude_none=True)


class PlaybookPublic(BaseModel):
    """The library card: what a reader needs, nothing the detector scores with.

    `retrieval_phrases` and `expected_indicators` stay behind the API. They are
    the detector's inputs, and publishing them is publishing what to avoid saying.
    """

    id: str
    region: str
    family: str
    name: dict[str, str]
    summary: dict[str, str]
    stages: dict[str, dict[str, str]]
    red_flags: dict[str, list[str]]
    action: ActionOut
    #: The number a verdict for this playbook shows.
    hotline: str
    hotlines: list[Hotline]
    sources: list[str]

    @classmethod
    def from_playbook(cls, playbook: Playbook) -> PlaybookPublic:
        action = playbook.action.model_dump(exclude_none=True)
        return cls(
            id=playbook.id,
            region=playbook.region,
            family=playbook.family,
            name=_present(playbook.name),
            summary=_present(playbook.summary),
            stages={str(stage): _present(text) for stage, text in playbook.stages.items()},
            red_flags=_present(playbook.red_flags),
            action=ActionOut(key=action.pop("key"), text=action),
            hotline=playbook.hotline,
            hotlines=list(playbook.hotlines),
            sources=list(playbook.sources),
        )


__all__ = ["ActionOut", "AnalyzeOut", "FeedbackIn", "HealthOut", "PlaybookPublic"]
