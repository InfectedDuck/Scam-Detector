"""Multi-provider OpenAI-compatible LLM client.

    from saqbol.llm import LLMClient
    judgement, stats = await LLMClient().structured(
        model="deepseek-chat", system=..., user=..., schema=LLMJudgement,
    )

Three properties the rest of the system relies on:

* **It returns a validated object or raises.** Never a partial one.
* **It is replayable.** Every successful call is written to `.cache/llm/`, and
  `SAQBOL_LLM_OFFLINE=1` turns that directory into the only source of truth, so
  CI runs the whole pipeline with no key and no network.
* **It records what it cost.** Every call returns `CallStats`, which is where
  the budget line and the leaderboard's cost column come from.
"""

from saqbol.llm.cache import CacheEntry, DiskCache, cache_key
from saqbol.llm.client import CallStats, LLMClient
from saqbol.llm.errors import (
    LLMError,
    OfflineCacheMiss,
    ProviderNotConfigured,
    SchemaViolation,
    TransientError,
    UnknownProvider,
)
from saqbol.llm.pricing import PRICES, price
from saqbol.llm.providers import DASHSCOPE, DEEPSEEK, OPENROUTER, Provider, resolve
from saqbol.llm.transport import OpenAITransport, RawCompletion, Transport

__all__ = [
    "DASHSCOPE",
    "DEEPSEEK",
    "OPENROUTER",
    "PRICES",
    "CacheEntry",
    "CallStats",
    "DiskCache",
    "LLMClient",
    "LLMError",
    "OfflineCacheMiss",
    "OpenAITransport",
    "Provider",
    "ProviderNotConfigured",
    "RawCompletion",
    "SchemaViolation",
    "TransientError",
    "Transport",
    "UnknownProvider",
    "cache_key",
    "price",
    "resolve",
]
