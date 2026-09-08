"""What the handlers need, built once per process.

A `Deps` object is attached to the app when it is created. Everything on it is
resolved on first use, under a lock, so importing `saqbol.api.main` never
opens a database, and a test can hand in an in-memory store and fixed limits
without touching the environment. Production resolves from the environment:

* `DATABASE_URL` set -> `Store.from_env()`; unset -> an in-memory SQLite
  store with a logged warning, so the server runs on a laptop with nothing
  configured;
* `ACTOR_HASH_SECRET` set -> that key; unset with the in-memory store -> a
  random key that dies with the process; unset with a real database -> the
  hashing module's own error at startup, because a persistent database with a
  guessable key is the outcome that module exists to prevent.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request

from saqbol import pipeline
from saqbol.core.types import Lang, Verdict
from saqbol.db import hashing
from saqbol.db.repo import Store
from saqbol.playbooks import loader
from saqbol.playbooks.schema import Playbook

log = logging.getLogger("saqbol.api")

#: Any of these being set means a model provider is configured.
PROVIDER_KEY_ENVS = ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "OPENROUTER_API_KEY")

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class _Unset:
    """Marker for "not resolved yet", for a dependency whose resolved value may be None."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive, got {value}")
    return value


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def _env_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


@dataclass(frozen=True)
class Settings:
    """Limits and switches. Defaults are the contract's numbers."""

    #: Characters of `text` per request.
    max_text_chars: int = 8000
    #: Decoded size of `image_b64` per request.
    max_image_bytes: int = 5 * 1024 * 1024
    #: Checks per actor per UTC day.
    daily_check_limit: int = 10
    #: Take the client address from X-Forwarded-For. Safe only behind a proxy
    #: that overwrites the header; otherwise anyone picks their own bucket.
    trust_proxy: bool = False
    #: Browser origins allowed to call the API. Empty means no CORS at all.
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        origins = os.environ.get("CORS_ORIGINS", "").split(",")
        return cls(
            max_text_chars=_env_int("MAX_TEXT_CHARS", cls.max_text_chars),
            max_image_bytes=_env_int("MAX_IMAGE_BYTES", cls.max_image_bytes),
            daily_check_limit=_env_int("DAILY_CHECK_LIMIT", cls.daily_check_limit),
            trust_proxy=_env_flag("TRUST_PROXY"),
            cors_origins=tuple(o.strip() for o in origins if o.strip()),
        )


class AnalyzeFn(Protocol):
    """The shape of `saqbol.pipeline.analyze`, so a test can substitute a stub."""

    async def __call__(
        self,
        text: str,
        *,
        locale: Lang | None = None,
        surface: str = "api",
        thread: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Verdict: ...


class Perceive(Protocol):
    """Screenshot bytes in, transcript text out. Raises on failure.

    The same seam the bot uses. An implementation must not keep, write or log
    the bytes; the handler drops its own reference the moment this returns.
    An empty string means the image held no readable message text.
    """

    async def __call__(self, image: bytes, *, locale: Lang | None) -> str: ...


def llm_configured() -> bool:
    """Whether a provider key is present. Never contacts a provider."""
    return any(_env_set(name) for name in PROVIDER_KEY_ENVS)


def vision_configured() -> bool:
    """Whether this process can read a screenshot. Never contacts a provider."""
    from saqbol.core.perceive import vision_available

    return vision_available()


def build_store() -> Store:
    if _env_set("DATABASE_URL"):
        return Store.from_env()
    log.warning(
        "DATABASE_URL is not set; using an in-memory SQLite store. "
        "Checks, votes and rate limits will not survive a restart."
    )
    return Store.in_memory()


def build_analyzer() -> AnalyzeFn:
    # Load the playbooks and the retrieval index now, not on the first request.
    pipeline.default_analyzer()
    return pipeline.analyze


def build_perceive() -> Perceive | None:
    """The screenshot reader, or None when this process cannot read one.

    A DashScope key, or offline replay mode with recorded cassettes, makes it
    available. Without either, `POST /api/v1/analyze` answers a screenshot
    with `image_not_supported` instead of spending a check on a call that
    cannot succeed.
    """
    if not vision_configured():
        log.info("no vision provider configured; screenshots are disabled")
        return None

    from saqbol.core.llm import LLMClient
    from saqbol.core.perceive import perceive

    client = LLMClient()

    async def call(image: bytes, *, locale: Lang | None) -> str:
        transcript, stats = await perceive(image, client=client, hint=locale)
        log.info(
            "screenshot read: model=%s turns=%d cached=%s latency_ms=%d",
            stats.model,
            len(transcript.turns),
            stats.cached,
            stats.latency_ms,
        )
        return transcript.render()

    return call


def build_actor_secret() -> bytes:
    if _env_set(hashing.SECRET_ENV) or _env_set("DATABASE_URL"):
        return hashing.actor_secret()
    log.warning(
        "%s is not set; hashing client addresses with a random key for this process only.",
        hashing.SECRET_ENV,
    )
    return secrets.token_bytes(32)


class Deps:
    """Per-process singletons. Pass any of them in to override the environment."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: Store | None = None,
        analyzer: AnalyzeFn | None = None,
        playbooks: dict[str, Playbook] | None = None,
        actor_secret: bytes | None = None,
        perceive: Perceive | _Unset | None = UNSET,
    ) -> None:
        self._settings = settings
        self._store = store
        self._analyzer = analyzer
        self._playbooks = playbooks
        self._actor_secret = actor_secret
        # None is a real value here ("screenshots off"), so absence needs its own marker.
        self._perceive: Perceive | _Unset | None = perceive
        self._lock = threading.Lock()

    def _once[T](self, attr: str, factory: Callable[[], T]) -> T:
        value = getattr(self, attr)
        if value is None:
            with self._lock:
                value = getattr(self, attr)
                if value is None:
                    value = factory()
                    setattr(self, attr, value)
        return value

    @property
    def settings(self) -> Settings:
        return self._once("_settings", Settings.from_env)

    @property
    def store(self) -> Store:
        return self._once("_store", build_store)

    @property
    def analyzer(self) -> AnalyzeFn:
        return self._once("_analyzer", build_analyzer)

    @property
    def playbooks(self) -> dict[str, Playbook]:
        return self._once("_playbooks", loader.registry)

    @property
    def actor_secret(self) -> bytes:
        return self._once("_actor_secret", build_actor_secret)

    @property
    def perceive(self) -> Perceive | None:
        if self._perceive is UNSET:
            with self._lock:
                if self._perceive is UNSET:
                    self._perceive = build_perceive()
        return None if self._perceive is UNSET else self._perceive

    def warm(self) -> None:
        """Resolve everything now, so a bad configuration fails at startup."""
        for name in ("settings", "store", "analyzer", "playbooks", "actor_secret", "perceive"):
            getattr(self, name)


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


DepsDep = Annotated[Deps, Depends(get_deps)]

__all__ = [
    "PROVIDER_KEY_ENVS",
    "AnalyzeFn",
    "Deps",
    "DepsDep",
    "Perceive",
    "Settings",
    "build_actor_secret",
    "build_analyzer",
    "build_perceive",
    "build_store",
    "get_deps",
    "llm_configured",
    "vision_configured",
]
