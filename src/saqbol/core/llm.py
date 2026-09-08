"""Multi-provider LLM client — stage 4's only route to a model.

    from saqbol.core.llm import LLMClient
    judgement, stats = await LLMClient().structured(
        model="deepseek-chat", system=..., user=..., schema=LLMJudgement,
    )

`structured` returns a validated pydantic object or raises. There is no third
outcome, and that is the point: the fusion stage reads `confidence` straight
into the risk score, so a half-parsed judgement with a defaulted 0.0 would not
look like a failure — it would look like a confident "not a scam", which is the
worst thing this system can output.

Four properties the rest of SaqBol depends on.

**No new dependencies.** All three providers speak the same chat-completions
shape over HTTPS, so this is `urllib` rather than a vendor SDK. `core/` keeps
its four pure-Python dependencies and a live call needs nothing installed that
the offline test suite does not already have.

**Replayable.** Every successful call is written to a cache directory, and
`SAQBOL_LLM_OFFLINE=1` makes that directory the only source of truth: a miss
raises instead of reaching the network. That is what lets T115 and T507 run the
whole pipeline in CI with no key.

**Refusals are an outcome, not an error.** Some safety-tuned models decline to
analyse impersonation content even when the request is plainly defensive. That
is a measurable property of the model and it belongs in the results table as a
column, so it is detected, never retried, and raised as its own type.

**Costs are unknown until checked.** `cost_usd` is None for any model whose
price is not in `PRICES`, and `PRICES` starts empty on purpose. A wrong number
in a published cost table is worse than an absent one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base for everything this module raises."""


class UnknownProvider(LLMError):
    """The model name matches no routing rule."""


class ProviderNotConfigured(LLMError):
    """The provider was resolved but its API key is absent."""


class TransientError(LLMError):
    """A 429, a 5xx, or a connection failure. Retryable with backoff."""


class SchemaViolation(LLMError):
    """Output that does not validate, twice. Never a partial object."""


class OfflineCacheMiss(LLMError):
    """`SAQBOL_LLM_OFFLINE` is set and the call is not in the cassette.

    Raised rather than silently reaching the network, so a test that drifts
    fails loudly in CI instead of hanging or costing money.
    """


class ModelRefused(LLMError):
    """The model declined to answer.

    Distinct from every other failure because it is a fact about the model
    rather than about our request, and the refusal rate is a published number.
    Never retried: a model that declines once declines again, and a retry loop
    would turn a data point into a bill.
    """

    def __init__(self, model: str, text: str) -> None:
        super().__init__(f"{model} declined: {text[:200]!r}")
        self.model = model
        self.text = text


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    name: str
    api_key_env: str
    base_url_env: str
    default_base_url: str


DEEPSEEK = Provider(
    name="deepseek",
    api_key_env="DEEPSEEK_API_KEY",
    base_url_env="DEEPSEEK_BASE_URL",
    default_base_url="https://api.deepseek.com",
)

DASHSCOPE = Provider(
    name="dashscope",
    api_key_env="DASHSCOPE_API_KEY",
    base_url_env="DASHSCOPE_BASE_URL",
    default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

OPENROUTER = Provider(
    name="openrouter",
    api_key_env="OPENROUTER_API_KEY",
    base_url_env="OPENROUTER_BASE_URL",
    default_base_url="https://openrouter.ai/api/v1",
)

PROVIDERS: dict[str, Provider] = {p.name: p for p in (DEEPSEEK, DASHSCOPE, OPENROUTER)}

#: Direct-endpoint prefixes, checked only after the slash rule in `resolve`.
_PREFIXES: tuple[tuple[str, Provider], ...] = (
    ("deepseek", DEEPSEEK),
    ("qwen", DASHSCOPE),
)


def resolve(model: str) -> Provider:
    """Route a model name to a provider.

    In order: an explicit ``provider:model`` prefix wins; then a ``/`` means
    OpenRouter, whose ids are always ``vendor/model``; then the vendor prefix
    picks the direct endpoint.

    The slash must be checked before the prefix, and that ordering is the whole
    reason this is a function rather than a dict lookup. ``deepseek-chat`` is
    DeepSeek's own endpoint; ``deepseek/deepseek-chat`` is the same model rented
    through OpenRouter for a leaderboard row. Both are used, they bill
    separately, and only the slash tells them apart.
    """
    name = model.strip()
    if not name:
        raise UnknownProvider("model name is empty")

    head, sep, rest = name.partition(":")
    if sep and head in PROVIDERS and rest:
        return PROVIDERS[head]

    if "/" in name:
        return OPENROUTER

    lowered = name.lower()
    for prefix, provider in _PREFIXES:
        if lowered.startswith(prefix):
            return provider

    raise UnknownProvider(
        f"no routing rule for model {model!r}. Direct endpoints match the "
        f"prefixes {[p for p, _ in _PREFIXES]}, an OpenRouter id contains a "
        f"'/', and any model can be forced with a '<provider>:' prefix from "
        f"{sorted(PROVIDERS)}."
    )


def wire_name(model: str) -> str:
    """The id the endpoint expects, with any forced ``provider:`` prefix removed."""
    head, sep, rest = model.partition(":")
    if sep and head in PROVIDERS and rest:
        return rest
    return model


def credentials(provider: Provider, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return ``(api_key, base_url)``, or explain precisely what is missing."""
    source = os.environ if env is None else env

    key = (source.get(provider.api_key_env) or "").strip()
    if not key:
        raise ProviderNotConfigured(
            f"{provider.api_key_env} is not set, so {provider.name} cannot be "
            f"called. Copy .env.example to .env and fill it in, or run with "
            f"SAQBOL_LLM_OFFLINE=1 to replay recorded responses instead."
        )

    base_url = (source.get(provider.base_url_env) or "").strip() or provider.default_base_url
    return key, base_url.rstrip("/")


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

#: Phrases that mark a decline rather than an answer. Deliberately short and
#: auditable: the refusal rate gets published, so the rule that produces it has
#: to be describable in a paper in one sentence.
REFUSAL_MARKERS: tuple[str, ...] = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i'm not able to help",
    "i won't be able to help",
    "unable to assist with that",
    "не могу помочь",
    "не могу выполнить",
    "я не могу предоставить",
    "无法提供帮助",
    "我不能协助",
)

#: A refusal states itself early. Only the head of the reply is checked, so an
#: analysis that quotes the phrase back to us is not miscounted as a refusal.
REFUSAL_WINDOW = 400


def looks_like_refusal(text: str) -> bool:
    lowered = text.strip().casefold()
    if not lowered:
        return False
    head = lowered[:REFUSAL_WINDOW]
    return any(marker in head for marker in REFUSAL_MARKERS)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

#: USD per one million tokens, ``(input, output)``.
#:
#: **Empty by design.** An entry is added only once that price has been read off
#: the provider's own pricing page, and the date of that check recorded in the
#: commit. Until then `price()` returns None and `CallStats.cost_usd` is None,
#: which is honest; a guessed rate here would silently become a wrong number in
#: the budget table of a published report.
PRICES: dict[str, tuple[float, float]] = {}


def price(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    rates = PRICES.get(model)
    if rates is None:
        return None
    per_in, per_out = rates
    return (prompt_tokens * per_in + completion_tokens * per_out) / 1_000_000


# ---------------------------------------------------------------------------
# Cache — also the cassette layer
# ---------------------------------------------------------------------------

#: Bumped when the entry shape changes, so old files are ignored rather than
#: misread.
CACHE_VERSION = 1

ENV_CACHE_DIR = "SAQBOL_LLM_CACHE_DIR"
ENV_OFFLINE = "SAQBOL_LLM_OFFLINE"
DEFAULT_CACHE_DIR = Path(".cache") / "llm"


class CacheEntry(BaseModel):
    version: int = CACHE_VERSION
    model: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    recorded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def cache_key(
    *,
    model: str,
    system: str,
    user: str,
    schema_name: str,
    temperature: float,
    images: Sequence[str] = (),
) -> str:
    """sha256 over everything that determines the response.

    Fields are length-prefixed rather than joined by a separator, so no
    combination of inputs can be rearranged into another's key. Images enter
    as their own digests, after the text fields, so a text-only call keeps the
    key it always had and a cassette recorded before images existed still
    replays.
    """
    digest = hashlib.sha256()
    parts = [str(CACHE_VERSION), model, system, user, schema_name, f"{temperature:.4f}"]
    parts.extend(hashlib.sha256(image.encode("utf-8")).hexdigest() for image in images)
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(f"{len(encoded)}\x00".encode("ascii"))
        digest.update(encoded)
    return digest.hexdigest()


class DiskCache:
    """Content-addressed, sharded one level to keep directories small.

    The cache is an optimisation, so nothing it does may ever fail a call. Both
    sides swallow everything rather than enumerating failure modes: a read-only
    volume raises OSError, a corrupt file raises JSONDecodeError, a path the
    platform rejects raises ValueError. Losing an entry costs a fraction of a
    cent; propagating the error loses the user's answer.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = os.environ.get(ENV_CACHE_DIR) or DEFAULT_CACHE_DIR
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        try:
            raw = self._path(key).read_text(encoding="utf-8")
            entry = CacheEntry.model_validate_json(raw)
        except Exception:
            return None
        return entry if entry.version == CACHE_VERSION else None

    def put(self, key: str, entry: CacheEntry) -> None:
        try:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Written to a temp file in the same directory then renamed, so a
            # crashed or concurrent run never leaves a half-written cassette
            # that a later run would read as truth.
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(entry.model_dump_json(indent=2))
                os.replace(tmp, path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        except Exception:
            return

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except Exception:
            return

    def __len__(self) -> int:
        if not self.root.exists():
            return 0
        return sum(1 for _ in self.root.rglob("*.json"))


# ---------------------------------------------------------------------------
# Transport — the network boundary
# ---------------------------------------------------------------------------


def _user_content(user: str, images: Sequence[str]) -> str | list[dict]:
    """A plain string for text, the multimodal parts list when images ride along.

    `images` are already data URLs (`data:image/jpeg;base64,...`); nothing here
    reads or stores bytes. Image parts go first so the text that follows can
    refer to "the screenshot above", which is how the OCR prompt is written.
    """
    if not images:
        return user
    parts: list[dict] = [{"type": "image_url", "image_url": {"url": url}} for url in images]
    parts.append({"type": "text", "text": user})
    return parts


@dataclass(frozen=True)
class RawCompletion:
    """What came back, before any schema thinking."""

    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@runtime_checkable
class Transport(Protocol):
    async def complete(
        self,
        *,
        provider: Provider,
        model: str,
        system: str,
        user: str,
        temperature: float,
        images: Sequence[str] = (),
    ) -> RawCompletion: ...


class HttpTransport:
    """`urllib` against the OpenAI chat-completions shape.

    Every provider on the leaderboard accepts this one request format, which is
    why four models cost one integration rather than four. The blocking call
    runs in a worker thread: the bot is aiogram and the graph is LangGraph, so a
    synchronous request on the event loop would stall every other user's message
    for the length of an LLM round trip.
    """

    def __init__(self, *, env: Mapping[str, str] | None = None, timeout: float = 60.0) -> None:
        self._env = env
        self._timeout = timeout

    def _post(self, url: str, headers: dict[str, str], body: dict) -> tuple[int, dict]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            try:
                payload = json.loads(err.read().decode("utf-8"))
            except Exception:
                payload = {"error": {"message": str(err.reason)}}
            return err.code, payload
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise TransientError(f"unreachable: {err}") from err

    async def complete(
        self,
        *,
        provider: Provider,
        model: str,
        system: str,
        user: str,
        temperature: float,
        images: Sequence[str] = (),
    ) -> RawCompletion:
        api_key, base_url = credentials(provider, self._env)
        body = {
            "model": wire_name(model),
            "temperature": temperature,
            # Accepted by all three. DeepSeek additionally requires the string
            # "json" somewhere in the prompt, which the schema block always
            # satisfies.
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": _user_content(user, images)},
            ],
        }
        if images and provider is DASHSCOPE:
            # Qwen3-VL is a hybrid model, and JSON mode is only honoured with
            # thinking off. Sent only on image calls so text calls keep the
            # exact body they had.
            body["enable_thinking"] = False
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        status, payload = await asyncio.to_thread(
            self._post, f"{base_url}/chat/completions", headers, body
        )

        if status == 429 or status >= 500:
            raise TransientError(f"{provider.name}: HTTP {status}")
        if status >= 400:
            # A 4xx other than 429 is our bug — a bad model id, a malformed
            # request — and retrying only burns the rate limit.
            message = (payload.get("error") or {}).get("message", payload)
            raise LLMError(f"{provider.name}: HTTP {status}: {message}")

        choices = payload.get("choices") or [{}]
        content = ((choices[0] or {}).get("message") or {}).get("content") or ""
        usage = payload.get("usage") or {}
        return RawCompletion(
            content=content,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

#: One original attempt plus exactly one repair. A model that cannot produce the
#: shape twice will not produce it on the third try, and the caller has a
#: deterministic fallback that is cheaper than another round trip.
_SCHEMA_ATTEMPTS = 2

_FENCE = re.compile(r"^\s*```(?:json)?\s*\n?(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)


class CallStats(BaseModel):
    """What one call cost, in every currency that matters.

    `cost_usd` is the priced value of the tokens whether or not they were billed
    this time, and None when the model's rate has not been verified; `cached`
    says whether money actually moved. Keeping both means an eval rerun off the
    cache can still report cost-per-check, while the budget line sums only the
    uncached rows.

    `retries` counts every attempt after the first, from either cause: a
    transient 429 or 5xx, and a schema repair.
    """

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    latency_ms: int
    cached: bool
    retries: int


def _strip_fence(content: str) -> str:
    match = _FENCE.match(content)
    return match.group("body") if match else content.strip()


def _loads(content: str) -> object:
    """Parse the reply as JSON, tolerating the two things models do anyway.

    JSON mode is requested on every call, so this is belt and braces: a markdown
    fence, or a sentence of preamble before the object.
    """
    body = _strip_fence(content)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass

    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise SchemaViolation(f"reply contains no JSON object: {content[:400]!r}")

    try:
        return json.loads(body[start : end + 1])
    except json.JSONDecodeError as err:
        raise SchemaViolation(f"reply is not valid JSON: {content[:400]!r}") from err


def _parse[T: BaseModel](content: str, schema: type[T]) -> T:
    payload = _loads(content)
    try:
        return schema.model_validate(payload)
    except ValidationError as err:
        raise SchemaViolation(str(err)) from err


def _schema_prompt(system: str, schema: type[BaseModel]) -> str:
    """Append the JSON Schema to the system prompt.

    `ensure_ascii=False` matters: field descriptions in this project are partly
    Cyrillic, and escaping them to \\uXXXX both wastes tokens and makes the
    prompt unreadable when debugging a bad response.
    """
    rendered = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        f"{system}\n\n"
        "Reply with a single JSON object and nothing else — no prose, no code "
        "fence. It must validate against this JSON Schema:\n"
        f"{rendered}"
    )


def _repair_prompt(user: str, previous: str, error: str) -> str:
    return (
        f"{user}\n\n"
        "Your previous reply was rejected because it did not match the required "
        "schema.\n\n"
        f"Previous reply:\n{previous[:2000]}\n\n"
        f"Validation error:\n{error[:2000]}\n\n"
        "Reply again with only the corrected JSON object."
    )


def _offline_from_env(env: Mapping[str, str]) -> bool:
    return (env.get(ENV_OFFLINE) or "").strip().lower() in {"1", "true", "yes", "on"}


class LLMClient:
    """Multi-provider, cached, schema-enforcing.

    Nothing here knows what a scam is. It is deliberately generic so the judge
    node, the refusal probe and the eval harness share one retry policy and one
    cost ledger.
    """

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        cache: DiskCache | bool | None = True,
        env: Mapping[str, str] | None = None,
        max_transport_attempts: int = 3,
        base_delay: float = 0.5,
        offline: bool | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._env: Mapping[str, str] = os.environ if env is None else env
        self._transport = transport or HttpTransport(env=self._env)

        if cache is True:
            self._cache: DiskCache | None = DiskCache()
        elif cache is False or cache is None:
            self._cache = None
        else:
            self._cache = cache

        self._max_transport_attempts = max(1, max_transport_attempts)
        self._base_delay = base_delay
        self._offline = _offline_from_env(self._env) if offline is None else offline
        self._sleep = sleep or asyncio.sleep

    @property
    def offline(self) -> bool:
        return self._offline

    async def structured[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        images: Sequence[str] = (),
    ) -> tuple[T, CallStats]:
        started = perf_counter()

        key = cache_key(
            model=model,
            system=system,
            user=user,
            schema_name=schema.__name__,
            temperature=temperature,
            images=images,
        )

        if self._cache is not None:
            hit = self._replay(key, schema, model, started)
            if hit is not None:
                return hit

        if self._offline:
            raise OfflineCacheMiss(
                f"{ENV_OFFLINE} is set and model {model!r} has no cassette for "
                f"this input (key {key[:12]}). Record it with a live key, or "
                f"fix the prompt that changed the key."
            )

        provider = resolve(model)
        system_prompt = _schema_prompt(system, schema)
        current_user = user
        retries = 0

        for attempt in range(_SCHEMA_ATTEMPTS):
            raw, transport_retries = await self._call(
                provider=provider,
                model=model,
                system=system_prompt,
                user=current_user,
                temperature=temperature,
                images=images,
            )
            retries += transport_retries

            # Checked before parsing, and never retried or cached. A decline is
            # a fact about the model, so repairing it would be measuring our own
            # persistence rather than the model's behaviour.
            if looks_like_refusal(raw.content):
                raise ModelRefused(model, raw.content)

            try:
                parsed = _parse(raw.content, schema)
            except SchemaViolation as err:
                if attempt + 1 == _SCHEMA_ATTEMPTS:
                    raise SchemaViolation(
                        f"{model} failed to produce valid {schema.__name__} after "
                        f"a repair attempt: {err}"
                    ) from err
                retries += 1
                current_user = _repair_prompt(user, raw.content, str(err))
                continue

            if self._cache is not None:
                self._cache.put(
                    key,
                    CacheEntry(
                        model=model,
                        content=raw.content,
                        prompt_tokens=raw.prompt_tokens,
                        completion_tokens=raw.completion_tokens,
                    ),
                )

            return parsed, CallStats(
                model=model,
                prompt_tokens=raw.prompt_tokens,
                completion_tokens=raw.completion_tokens,
                cost_usd=price(model, raw.prompt_tokens, raw.completion_tokens),
                latency_ms=_elapsed_ms(started),
                cached=False,
                retries=retries,
            )

        raise AssertionError("unreachable: the loop either returns or raises")

    def _replay[T: BaseModel](
        self, key: str, schema: type[T], model: str, started: float
    ) -> tuple[T, CallStats] | None:
        assert self._cache is not None

        entry = self._cache.get(key)
        if entry is None:
            return None

        try:
            parsed = _parse(entry.content, schema)
        except SchemaViolation as err:
            # The cassette predates a change to `schema`. Offline there is no
            # way forward and silence would misreport what was replayed; online,
            # the honest move is to discard it and record a fresh one.
            if self._offline:
                raise SchemaViolation(
                    f"cassette {key[:12]} no longer validates against "
                    f"{schema.__name__}: {err}. Re-record it with a live key."
                ) from err
            self._cache.delete(key)
            return None

        return parsed, CallStats(
            model=model,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            cost_usd=price(model, entry.prompt_tokens, entry.completion_tokens),
            latency_ms=_elapsed_ms(started),
            cached=True,
            retries=0,
        )

    async def _call(
        self,
        *,
        provider: Provider,
        model: str,
        system: str,
        user: str,
        temperature: float,
        images: Sequence[str] = (),
    ) -> tuple[RawCompletion, int]:
        """One logical request, retrying transient failures with backoff."""
        retries = 0
        delay = self._base_delay
        # Passed only when present, so a transport written before images
        # existed — every fake in the test suite included — keeps working.
        extra: dict = {"images": tuple(images)} if images else {}

        while True:
            try:
                raw = await self._transport.complete(
                    provider=provider,
                    model=model,
                    system=system,
                    user=user,
                    temperature=temperature,
                    **extra,
                )
                return raw, retries
            except TransientError:
                if retries + 1 >= self._max_transport_attempts:
                    raise
                # Jitter keeps parallel eval workers from retrying in lockstep
                # and re-triggering the same rate limit.
                await self._sleep(delay * (1.0 + random.random() * 0.25))
                retries += 1
                delay *= 2


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
