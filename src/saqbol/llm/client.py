"""The client the rest of SaqBol calls.

One method, `structured`, which either returns a validated pydantic object or
raises. There is no third outcome: the judge node in graph.py has to be able to
assume that a returned `LLMJudgement` is well-formed, because the fusion stage
reads its `confidence` directly into the risk score. A partially-parsed object
with a defaulted confidence of 0.0 would not look like a failure — it would
look like a confident "not a scam", which is the single worst thing this system
can output.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter

from pydantic import BaseModel, ValidationError

from saqbol.llm.cache import CacheEntry, DiskCache, cache_key
from saqbol.llm.errors import OfflineCacheMiss, SchemaViolation, TransientError
from saqbol.llm.pricing import price
from saqbol.llm.providers import resolve
from saqbol.llm.transport import OpenAITransport, RawCompletion, Transport

ENV_OFFLINE = "SAQBOL_LLM_OFFLINE"

#: One original attempt plus exactly one repair. A model that cannot produce the
#: shape twice will not produce it on the third try either, and the caller has a
#: deterministic fallback that is cheaper than another round trip.
_SCHEMA_ATTEMPTS = 2

_FENCE = re.compile(r"^\s*```(?:json)?\s*\n?(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)


class CallStats(BaseModel):
    """What one call cost, in every currency that matters.

    `cost_usd` is always the priced value of the tokens, whether or not they
    were billed this time; `cached` says whether money actually moved. Keeping
    both means the eval can report cost-per-check honestly from a cached rerun,
    while the budget line sums only the uncached rows. Collapsing them would
    lose one number or the other.

    `retries` counts every attempt after the first, from either cause: a
    transient 429 or 5xx, and a schema repair.
    """

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    cached: bool
    retries: int


def _strip_fence(content: str) -> str:
    match = _FENCE.match(content)
    return match.group("body") if match else content.strip()


def _loads(content: str) -> object:
    """Parse the model's reply as JSON, tolerating the two things models do anyway.

    JSON mode is requested on every call, so this is a belt-and-braces path:
    a markdown fence, or a sentence of preamble before the object.
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

    Nothing here knows what a scam is. It is deliberately generic so that the
    refusal probe, the judge node and the eval harness all share one retry
    policy and one cost ledger.
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
        self._transport = (
            transport if transport is not None else OpenAITransport(env=dict(self._env))
        )

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
    ) -> tuple[T, CallStats]:
        started = perf_counter()

        key = cache_key(
            model=model,
            system=system,
            user=user,
            schema_name=schema.__name__,
            temperature=temperature,
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
        raw = RawCompletion(content="")

        for attempt in range(_SCHEMA_ATTEMPTS):
            raw, transport_retries = await self._call(
                provider=provider,
                model=model,
                system=system_prompt,
                user=current_user,
                temperature=temperature,
            )
            retries += transport_retries

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
            # way forward and silence would be a lie about what was replayed;
            # online, the honest move is to discard it and record a fresh one.
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
        provider,
        model: str,
        system: str,
        user: str,
        temperature: float,
    ) -> tuple[RawCompletion, int]:
        """One logical request, retrying transient failures with backoff."""
        retries = 0
        delay = self._base_delay

        while True:
            try:
                raw = await self._transport.complete(
                    provider=provider,
                    model=model,
                    system=system,
                    user=user,
                    temperature=temperature,
                )
                return raw, retries
            except TransientError:
                if retries + 1 >= self._max_transport_attempts:
                    raise
                # Jitter keeps several eval workers from retrying in lockstep
                # and re-triggering the same rate limit.
                await self._sleep(delay * (1.0 + random.random() * 0.25))
                retries += 1
                delay *= 2


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
