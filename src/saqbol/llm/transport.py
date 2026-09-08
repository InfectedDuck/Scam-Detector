"""The network boundary.

Everything above this file — caching, schema repair, backoff, costing — is pure
logic over a `Transport`. That split is what lets the whole client be tested
with no key, no network and no recorded fixtures, and it is why `openai` is
imported lazily inside the one method that needs it: importing this module must
stay free for the offline core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from saqbol.llm.errors import TransientError
from saqbol.llm.providers import Provider, credentials, wire_name


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
    ) -> RawCompletion: ...


class OpenAITransport:
    """One `AsyncOpenAI` per provider, pointed at that provider's base URL.

    All three providers speak the same wire format, which is the entire reason
    the leaderboard can hold four models without four integrations.
    """

    def __init__(self, *, env: dict[str, str] | None = None, timeout: float = 60.0) -> None:
        self._env = env
        self._timeout = timeout
        self._clients: dict[str, object] = {}

    def _client(self, provider: Provider):
        cached = self._clients.get(provider.name)
        if cached is not None:
            return cached

        from openai import AsyncOpenAI

        api_key, base_url = credentials(provider, self._env)
        client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=self._timeout, max_retries=0
        )
        self._clients[provider.name] = client
        return client

    async def complete(
        self,
        *,
        provider: Provider,
        model: str,
        system: str,
        user: str,
        temperature: float,
    ) -> RawCompletion:
        import openai

        client = self._client(provider)

        try:
            response = await client.chat.completions.create(
                model=wire_name(model),
                temperature=temperature,
                # Every provider here accepts json_object. DeepSeek additionally
                # requires the string "json" to appear in the prompt, which the
                # schema block in client.py always satisfies.
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except openai.RateLimitError as err:
            raise TransientError(f"{provider.name}: rate limited") from err
        except (openai.APIConnectionError, openai.APITimeoutError) as err:
            raise TransientError(f"{provider.name}: {type(err).__name__}") from err
        except openai.APIStatusError as err:
            if err.status_code >= 500:
                raise TransientError(f"{provider.name}: HTTP {err.status_code}") from err
            # 4xx other than 429 is our bug — a bad model id, a malformed
            # request — and retrying it just burns the rate limit.
            raise

        choice = response.choices[0]
        usage = response.usage
        return RawCompletion(
            content=choice.message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
