"""Per-model prices, in one place.

The budget line in docs/01_ARCHITECTURE.md section 7 and the cost column of the
leaderboard both resolve to this table. It is the only place a price appears.

Prices are USD per one million tokens.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

#: When the figures below were last read off the providers' public pricing
#: pages. **These have not been verified against a live page.** They are
#: carried from provider documentation and they drift — DeepSeek in particular
#: has changed pricing more than once and runs off-peak discounts.
#:
#: Before any cost number is published (T604 report, T605 one-pager), open the
#: three pricing pages, correct this table, and set this constant to that date
#: in the same commit. A stale price here becomes a wrong number in a PDF.
CHECKED_ON = "UNVERIFIED — see module docstring before publishing any cost"

#: model id → (input USD per 1M tokens, output USD per 1M tokens)
PRICES: dict[str, tuple[float, float]] = {
    # DeepSeek, direct endpoint. Cache-miss input pricing.
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    # Alibaba Cloud International, OpenAI-compatible mode.
    "qwen-plus": (0.40, 1.20),
    "qwen-turbo": (0.05, 0.20),
    "qwen-max": (1.60, 6.40),
    "qwen-vl-plus": (0.21, 0.63),
    # OpenRouter. Leaderboard rows only, never the hot path.
    "openai/gpt-4o-mini": (0.15, 0.60),
    "meta-llama/llama-3.3-70b-instruct": (0.12, 0.30),
    "deepseek/deepseek-chat": (0.27, 1.10),
}

_warned: set[str] = set()


def price(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost of one call in USD.

    An unpriced model returns 0.0 with a warning rather than raising. A missing
    price should not be able to fail a real analysis for a user mid-scam; it is
    a bookkeeping problem, and `test_llm_client.py` asserts that every model in
    the table is priced so the gap surfaces in CI instead.
    """
    rates = PRICES.get(model)
    if rates is None:
        if model not in _warned:
            _warned.add(model)
            _log.warning(
                "no price for model %r — cost recorded as 0.0. Add it to "
                "saqbol.llm.pricing.PRICES before reporting spend.",
                model,
            )
        return 0.0

    per_in, per_out = rates
    return (prompt_tokens * per_in + completion_tokens * per_out) / 1_000_000
