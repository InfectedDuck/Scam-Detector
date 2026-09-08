"""Multi-provider LLM client.

Every provider on the leaderboard speaks the OpenAI chat-completions shape, so
this is a thin, dependency-free client over `urllib` rather than a vendor SDK.
That keeps the package installable with four pure-Python dependencies and makes
the whole thing trivially mockable in tests.

Four things it does that a bare HTTP call does not:

* **Caches on disk** by model, prompt and parameters. A leaderboard rerun costs
  nothing and the exact response behind a published number stays inspectable,
  which is what makes the evaluation reproducible.
* **Enforces the output schema.** The judge returns a validated object or the
  call fails; it never returns prose the pipeline has to guess at.
* **Counts refusals as an outcome, not an error.** Some safety-tuned models
  decline to analyse impersonation content even when the request is defensive.
  That is a measurable property of the model and belongs in the results table,
  not in an exception.
* **Retries on transient failures only**, with backoff, and never on a refusal.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

DEFAULT_TIMEOUT = 90.0
DEFAULT_MAX_RETRIES = 3
BACKOFF_BASE = 1.5
CACHE_DIR = Path(os.environ.get("SAQBOL_LLM_CACHE", ".cache/llm"))

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """Terminal failure. `code` is stable; branch on it, not on the message."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Provider:
    name: str
    base_url_env: str
    api_key_env: str
    default_base_url: str
    #: Providers differ on whether they honour a strict JSON schema. When false
    #: the schema is described in the prompt and validated after the fact.
    supports_json_schema: bool = False

    def base_url(self) -> str:
        return os.environ.get(self.base_url_env) or self.default_base_url

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


PROVIDERS: dict[str, Provider] = {
    "deepseek": Provider(
        name="deepseek",
        base_url_env="DEEPSEEK_BASE_URL",
        api_key_env="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com",
    ),
    "dashscope": Provider(
        name="dashscope",
        base_url_env="DASHSCOPE_BASE_URL",
        api_key_env="DASHSCOPE_API_KEY",
        default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url_env="OPENROUTER_BASE_URL",
        api_key_env="OPENROUTER_API_KEY",
        default_base_url="https://openrouter.ai/api/v1",
        supports_json_schema=True,
    ),
}


@dataclass(frozen=True)
class ModelSpec:
    """One row of the leaderboard.

    `usd_per_million_in/out` are left as None until each price is checked
    against the provider's own page. A wrong price in a published cost table is
    worse than an absent one, so unknown stays unknown and `cost_usd` is None.
    """

    key: str
    provider: str
    model: str
    usd_per_million_in: float | None = None
    usd_per_million_out: float | None = None


MODELS: dict[str, ModelSpec] = {
    "deepseek-v3": ModelSpec("deepseek-v3", "deepseek", "deepseek-chat"),
    "qwen3": ModelSpec("qwen3", "dashscope", "qwen-plus"),
    "gpt-4o-mini": ModelSpec("gpt-4o-mini", "openrouter", "openai/gpt-4o-mini"),
    "llama-3.3-70b": ModelSpec("llama-3.3-70b", "openrouter", "meta-llama/llama-3.3-70b-instruct"),
}

#: Phrases that mark a decline rather than an answer. Deliberately short and
#: auditable; the refusal RATE is reported, so the rule that produces it has to
#: be describable in a paper.
REFUSAL_MARKERS = (
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


@dataclass
class LLMResponse:
    text: str
    model: str
    parsed: Any = None
    cached: bool = False
    refused: bool = False
    attempts: int = 1
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    raw: dict = field(default_factory=dict)


def looks_like_refusal(text: str) -> bool:
    lowered = text.strip().casefold()
    if not lowered:
        return False
    # A refusal states itself early. Checking a prefix avoids matching an
    # analysis that merely quotes the phrase.
    head = lowered[:400]
    return any(marker in head for marker in REFUSAL_MARKERS)


def _cache_key(model: str, payload: dict) -> str:
    blob = json.dumps({"model": model, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cost(
    spec: ModelSpec, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    if spec.usd_per_million_in is None or spec.usd_per_million_out is None:
        return None
    if prompt_tokens is None or completion_tokens is None:
        return None
    return (
        prompt_tokens * spec.usd_per_million_in / 1_000_000
        + completion_tokens * spec.usd_per_million_out / 1_000_000
    )


class LLMClient:
    """Chat completions across providers, with a disk cache and schema enforcement."""

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport=None,
        sleep=time.sleep,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
        self.timeout = timeout
        self.max_retries = max_retries
        #: Injected in tests. Signature: (url, headers, body) -> (status, dict)
        self._transport = transport or self._http_post
        self._sleep = sleep
        self.calls_made = 0

    # -- transport ---------------------------------------------------------

    def _http_post(self, url: str, headers: dict, body: dict) -> tuple[int, dict]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            try:
                payload = json.loads(err.read().decode("utf-8"))
            except Exception:
                payload = {"error": {"message": err.reason}}
            return err.code, payload
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise LLMError("unreachable", str(err)) from err

    # -- cache -------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    # The cache is an optimisation. Nothing it does may ever fail a call, so
    # both sides swallow everything rather than enumerating failure modes: a
    # read-only volume raises OSError, a corrupt file raises JSONDecodeError,
    # and a path the platform rejects raises ValueError. Losing a cache entry
    # costs a few cents; propagating the error loses the user's answer.

    def _read_cache(self, key: str) -> dict | None:
        try:
            path = self._cache_path(key)
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, key: str, payload: dict) -> None:
        try:
            path = self._cache_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # -- public API --------------------------------------------------------

    def complete(
        self,
        messages: list[dict],
        *,
        model: str = "deepseek-v3",
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        use_cache: bool = True,
        schema_retries: int = 1,
    ) -> LLMResponse:
        """One completion, validated against `schema` when given."""
        spec = MODELS.get(model)
        if spec is None:
            raise LLMError("unknown_model", f"{model!r} is not in MODELS")
        provider = PROVIDERS[spec.provider]

        conversation = list(messages)
        if schema is not None and not provider.supports_json_schema:
            conversation = self._describe_schema_in_prompt(conversation, schema)

        attempt = 0
        last_error = ""
        while True:
            attempt += 1
            payload = self._build_payload(
                spec, provider, conversation, schema, temperature, max_tokens
            )
            response = self._send(spec, provider, payload, use_cache=use_cache)
            response.attempts = attempt

            if schema is None or response.refused:
                return response

            try:
                response.parsed = schema.model_validate_json(_extract_json(response.text))
                return response
            except (ValidationError, ValueError, json.JSONDecodeError) as err:
                last_error = str(err)[:500]
                if attempt > schema_retries:
                    raise LLMError(
                        "schema_violation",
                        f"{model} did not produce valid output after {attempt} attempts: "
                        f"{last_error}",
                    ) from err
                # Show the model its own mistake. Caching is bypassed on the
                # retry so it does not simply replay the invalid answer.
                conversation = [
                    *conversation,
                    {"role": "assistant", "content": response.text},
                    {
                        "role": "user",
                        "content": (
                            "That did not match the required JSON schema. Error:\n"
                            f"{last_error}\n\nReturn ONLY the corrected JSON object."
                        ),
                    },
                ]
                use_cache = False

    # -- internals ---------------------------------------------------------

    def _build_payload(
        self,
        spec: ModelSpec,
        provider: Provider,
        messages: list[dict],
        schema: type[BaseModel] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            if provider.supports_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _describe_schema_in_prompt(messages: list[dict], schema: type[BaseModel]) -> list[dict]:
        instruction = (
            "Respond with a single JSON object and nothing else. No prose, no code "
            "fence. It must validate against this JSON Schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
        return [*messages, {"role": "system", "content": instruction}]

    def _send(
        self, spec: ModelSpec, provider: Provider, payload: dict, *, use_cache: bool
    ) -> LLMResponse:
        key = _cache_key(spec.key, payload)
        if use_cache:
            hit = self._read_cache(key)
            if hit is not None:
                return LLMResponse(
                    text=hit["text"],
                    model=spec.key,
                    cached=True,
                    refused=hit.get("refused", False),
                    prompt_tokens=hit.get("prompt_tokens"),
                    completion_tokens=hit.get("completion_tokens"),
                    cost_usd=hit.get("cost_usd"),
                    raw=hit.get("raw", {}),
                )

        api_key = provider.api_key()
        if not api_key:
            raise LLMError(
                "no_api_key",
                f"{provider.api_key_env} is not set, so {spec.key} cannot be called",
            )

        url = provider.base_url().rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        started = time.monotonic()
        body = self._send_with_retries(url, headers, payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        text = _first_message_content(body)
        usage = body.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        response = LLMResponse(
            text=text,
            model=spec.key,
            refused=looks_like_refusal(text),
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=_cost(spec, prompt_tokens, completion_tokens),
            raw=body,
        )

        self._write_cache(
            key,
            {
                "text": response.text,
                "refused": response.refused,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": response.cost_usd,
                "raw": body,
            },
        )
        return response

    def _send_with_retries(self, url: str, headers: dict, payload: dict) -> dict:
        for attempt in range(1, self.max_retries + 1):
            self.calls_made += 1
            status, body = self._transport(url, headers, payload)
            if status == 200:
                return body

            message = ((body or {}).get("error") or {}).get("message") or str(body)[:200]
            if status in RETRYABLE_STATUS and attempt < self.max_retries:
                self._sleep(BACKOFF_BASE**attempt)
                continue
            if status in (401, 403):
                raise LLMError("auth_failed", message, status=status)
            if status == 429:
                raise LLMError("rate_limited", message, status=status)
            raise LLMError("provider_error", message, status=status)

        raise LLMError("provider_error", "retries exhausted")


def _first_message_content(body: dict) -> str:
    try:
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as err:
        raise LLMError("bad_response", f"no message content in {str(body)[:200]}") from err


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may be fenced or padded.

    Providers without strict schema support wrap the object in prose or a code
    fence often enough that being tolerant here is cheaper than a retry.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in {text[:200]!r}")
    return stripped[start : end + 1]
