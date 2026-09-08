"""The seam between the bot and the rest of the system.

The bot needs two things it does not own: something that analyses a message and
something that renders the result. Both are being written in parallel lanes, so
they are declared here as protocols and satisfied by stubs until the real
modules land. When they do, **this file is the only one that changes** — no
handler imports `saqbol.core.render` or `saqbol.pipeline` directly.

The pinned signatures are:

    # saqbol/core/render.py
    class Card(BaseModel):
        title: str; band_label: str; summary: str
        evidence: list[str]; stage_now: str | None; stage_next: str | None
        action: str; hotlines: list[tuple[str, str]]; footer: str

    def render_card(verdict: Verdict, locale: Lang) -> Card: ...

    # saqbol/pipeline.py
    async def analyze(text: str, *, locale: Lang, surface: str) -> Verdict: ...

`analyze` as pinned takes neither the forwarded-message metadata that family I
reads nor the assembled thread that stage detection reads, and the bot is the
only place either of those exists. Rather than redesign a frozen contract, the
bot calls a superset — `thread=` and `metadata=` as optional keywords — and
`adapt_analyze` below drops whichever of them the real function turns out not to
accept, loudly. That keeps the pinned signature valid and confines the
adaptation to this one file.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol, runtime_checkable

from saqbol.bot.config import BotConfig
from saqbol.bot.storage import BotStore
from saqbol.core.types import Band, Components, EvidenceSpan, Lang, Stage, Verdict

log = logging.getLogger(__name__)


# --------------------------------------------------------------- protocols


@runtime_checkable
class Card(Protocol):
    """A rendered verdict, already localized. The bot only formats it."""

    title: str
    band_label: str
    summary: str
    evidence: list[str]
    stage_now: str | None
    stage_next: str | None
    action: str
    hotlines: list[tuple[str, str]]
    footer: str


class RenderCard(Protocol):
    def __call__(self, verdict: Verdict, locale: Lang) -> Card: ...


class Analyze(Protocol):
    async def __call__(
        self,
        text: str,
        *,
        locale: Lang,
        surface: str,
        thread: Sequence[str] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Verdict: ...


# ------------------------------------------------------------------- stubs


@dataclass
class StubCard:
    """Structural stand-in for `saqbol.core.render.Card`."""

    title: str
    band_label: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    stage_now: str | None = None
    stage_next: str | None = None
    action: str = ""
    hotlines: list[tuple[str, str]] = field(default_factory=list)
    footer: str = ""


#: Marks every stub output, so a fixture verdict reaching a screenshot or a demo
#: is recognisable rather than mistaken for a real one.
STUB_MARKER = "[stub]"


def stub_render_card(verdict: Verdict, locale: Lang) -> StubCard:
    playbook = verdict.playbook_id or "none"
    return StubCard(
        title=f"{STUB_MARKER} {verdict.band.value}",
        band_label=verdict.band.value,
        summary=f"risk {verdict.risk:.2f}, playbook {playbook}",
        evidence=[span.text for span in verdict.evidence],
        stage_now=verdict.stage.value if verdict.stage else None,
        stage_next=None,
        action=verdict.action_key or "call_your_bank",
        hotlines=[("102", "102")],
        footer=f"{STUB_MARKER} renderer not wired yet (locale {locale.value})",
    )


async def stub_analyze(
    text: str,
    *,
    locale: Lang,
    surface: str,
    thread: Sequence[str] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Verdict:
    """A fixture verdict with the shape of a real one.

    The evidence span is a genuine slice of the input rather than invented text,
    so the D4 invariant `text[start:end] == span.text` holds for stub output too
    and any test asserting on it is testing something real.
    """
    quote = text[:40]
    spans = [EvidenceSpan(start=0, end=len(quote), text=quote, indicator_id="stub")]
    return Verdict(
        check_id=sha256(text.encode("utf-8")).hexdigest()[:16],
        band=Band.SUSPICIOUS,
        risk=0.5,
        playbook_id=None,
        playbook_confidence=0.0,
        stage=Stage.CONTACT if thread and len(thread) > 1 else None,
        evidence=spans if quote else [],
        action_key="call_your_bank",
        hotline="102",
        language=locale,
        components=Components(rule_norm=0.5, retrieval_sim=0.0, llm_conf=0.5),
        model=STUB_MARKER,
    )


# -------------------------------------------------------------- adaptation


def adapt_analyze(fn: Callable) -> Analyze:
    """Wrap an `analyze` so the bot may always pass `thread` and `metadata`.

    Anything the wrapped function does not declare is dropped. Dropping
    `metadata` is warned about once, because it disables family I without
    failing, and a silently disabled indicator family is the kind of thing only
    noticed in the evaluation numbers weeks later.
    """
    params = inspect.signature(fn).parameters
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    takes_thread = accepts_kwargs or "thread" in params
    takes_metadata = accepts_kwargs or "metadata" in params

    if not takes_metadata:
        log.warning(
            "%s.%s does not accept metadata=; forwarded-message signals "
            "(indicator family I) will not reach the pipeline",
            getattr(fn, "__module__", "?"),
            getattr(fn, "__qualname__", "?"),
        )

    async def call(
        text: str,
        *,
        locale: Lang,
        surface: str,
        thread: Sequence[str] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Verdict:
        extra: dict = {}
        if takes_thread and thread is not None:
            extra["thread"] = list(thread)
        if takes_metadata and metadata is not None:
            extra["metadata"] = dict(metadata)
        return await fn(text, locale=locale, surface=surface, **extra)

    return call


# -------------------------------------------------------------------- deps


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Deps:
    """Everything a handler is allowed to reach for.

    Handlers receive this as an aiogram middleware value. They import no module
    another lane owns, which is what makes them testable with no network, no
    token and no database.
    """

    config: BotConfig
    store: BotStore
    analyze: Analyze
    render_card: RenderCard
    now: Callable[[], datetime] = utcnow
    #: True while the corresponding lane has not landed. Surfaced in `/help`, so
    #: a tester is never shown a fixture verdict without being told.
    analyze_is_stub: bool = False
    renderer_is_stub: bool = False


def build_deps(
    config: BotConfig,
    *,
    store: BotStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> Deps:
    """Resolve the real implementations, falling back to the stubs.

    Import failure is the expected path until the two lanes land, so it is
    logged at info rather than treated as an error.
    """
    analyze: Analyze = stub_analyze
    analyze_is_stub = True
    try:
        from saqbol.pipeline import analyze as real_analyze
    except ImportError:
        log.info("saqbol.pipeline is not available yet; using the stub analyzer")
    else:
        analyze = adapt_analyze(real_analyze)
        analyze_is_stub = False

    render_card: RenderCard = stub_render_card
    renderer_is_stub = True
    try:
        from saqbol.core.render import render_card as real_render_card
    except ImportError:
        log.info("saqbol.core.render is not available yet; using the stub renderer")
    else:
        render_card = real_render_card
        renderer_is_stub = False

    return Deps(
        config=config,
        store=store if store is not None else BotStore(config.state_path),
        analyze=analyze,
        render_card=render_card,
        now=now or utcnow,
        analyze_is_stub=analyze_is_stub,
        renderer_is_stub=renderer_is_stub,
    )
