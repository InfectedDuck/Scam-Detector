"""Provider routing.

Three OpenAI-compatible endpoints, chosen by the shape of the model name. The
environment variable names here must match `.env.example` exactly; they are
the same names the deployment sets.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from saqbol.llm.errors import ProviderNotConfigured, UnknownProvider


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

#: Direct-endpoint model prefixes. Checked only after the slash rule below.
_PREFIXES: tuple[tuple[str, Provider], ...] = (
    ("deepseek", DEEPSEEK),
    ("qwen", DASHSCOPE),
)


def resolve(model: str) -> Provider:
    """Route a model name to a provider.

    The rule, in order:

    1. A ``provider:model`` prefix is explicit and wins outright.
    2. A ``/`` in the name means OpenRouter, whose ids are always
       ``vendor/model``.
    3. Otherwise the vendor prefix picks the direct endpoint.

    Rule 2 must precede rule 3, and the ordering is the whole reason this is a
    function rather than a dict lookup. ``deepseek-chat`` is DeepSeek's own
    endpoint; ``deepseek/deepseek-chat`` is the same model rented through
    OpenRouter for a leaderboard row. Both are used, they cost different
    amounts, and only the slash tells them apart.
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
    """The model id as the endpoint expects it, with any ``provider:`` prefix removed."""
    head, sep, rest = model.partition(":")
    if sep and head in PROVIDERS and rest:
        return rest
    return model


def credentials(provider: Provider, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return ``(api_key, base_url)`` or explain precisely what is missing."""
    source = os.environ if env is None else env

    key = (source.get(provider.api_key_env) or "").strip()
    if not key:
        raise ProviderNotConfigured(
            f"{provider.api_key_env} is not set, so {provider.name} cannot be "
            f"called. Copy .env.example to .env and fill it in, or run with "
            f"SAQBOL_LLM_OFFLINE=1 to replay recorded responses instead."
        )

    base_url = (source.get(provider.base_url_env) or "").strip() or provider.default_base_url
    return key, base_url
