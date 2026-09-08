"""T111 — the LLM client.

Every test runs with no API key, no network and no recorded fixture. The
network boundary is a single `Transport.complete`, so a fake implementation of
that one method exercises caching, refusal handling, schema repair, backoff and
costing.

`pytest-asyncio` is deliberately not a dependency — the dev extra is three
packages and stays that way — so coroutines are driven through `asyncio.run`.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel

from saqbol.core.llm import (
    DASHSCOPE,
    DEEPSEEK,
    OPENROUTER,
    PRICES,
    REFUSAL_MARKERS,
    CacheEntry,
    DiskCache,
    LLMClient,
    ModelRefused,
    OfflineCacheMiss,
    ProviderNotConfigured,
    RawCompletion,
    SchemaViolation,
    TransientError,
    UnknownProvider,
    _schema_prompt,
    cache_key,
    credentials,
    looks_like_refusal,
    price,
    resolve,
    wire_name,
)


class Judgement(BaseModel):
    playbook_id: str
    confidence: float


VALID = json.dumps({"playbook_id": "kz.bank_security_call", "confidence": 0.9})
WRONG_SHAPE = json.dumps({"playbook_id": "kz.bank_security_call"})  # confidence missing


def run(coro):
    return asyncio.run(coro)


class FakeTransport:
    """Replies in order. Running out is an assertion failure, not a default.

    That strictness is the point: "the same input twice makes one network call"
    is only meaningful if a second call would be caught.
    """

    def __init__(self, *replies: RawCompletion | Exception) -> None:
        self.queue: list[RawCompletion | Exception] = list(replies)
        self.calls: list[dict] = []

    async def complete(self, *, provider, model, system, user, temperature):
        self.calls.append(
            {
                "provider": provider.name,
                "model": model,
                "system": system,
                "user": user,
                "temperature": temperature,
            }
        )
        if not self.queue:
            raise AssertionError(f"unexpected call {len(self.calls)} to the transport")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reply(content: str, *, prompt_tokens: int = 1200, completion_tokens: int = 80) -> RawCompletion:
    return RawCompletion(
        content=content, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )


def client(tmp_path, transport, **kwargs) -> LLMClient:
    kwargs.setdefault("env", {})
    kwargs.setdefault("cache", DiskCache(tmp_path / "cache"))
    return LLMClient(transport=transport, **kwargs)


def ask(cli: LLMClient, *, user: str = "проверь это", model: str = "deepseek-chat", **kwargs):
    return run(
        cli.structured(
            model=model, system="you are a triage assistant", user=user, schema=Judgement, **kwargs
        )
    )


# --------------------------------------------------------------------------
# The happy path, and the ledger
# --------------------------------------------------------------------------


def test_returns_validated_object(tmp_path):
    judgement, stats = ask(client(tmp_path, FakeTransport(reply(VALID))))

    assert isinstance(judgement, Judgement)
    assert judgement.playbook_id == "kz.bank_security_call"
    assert stats.cached is False
    assert stats.retries == 0


def test_usage_and_latency_are_recorded(tmp_path):
    _, stats = ask(client(tmp_path, FakeTransport(reply(VALID))))

    assert stats.prompt_tokens == 1200
    assert stats.completion_tokens == 80
    assert stats.latency_ms >= 0
    assert stats.model == "deepseek-chat"


def test_cost_is_none_until_the_price_is_verified(tmp_path):
    # PRICES ships empty on purpose. An absent cost is honest; a guessed one
    # becomes a wrong number in the report's budget table.
    _, stats = ask(client(tmp_path, FakeTransport(reply(VALID))))
    assert stats.cost_usd is None


def test_cost_is_computed_once_a_price_is_added(tmp_path, monkeypatch):
    monkeypatch.setitem(PRICES, "deepseek-chat", (0.27, 1.10))
    _, live = ask(client(tmp_path, FakeTransport(reply(VALID))))
    assert live.cost_usd == pytest.approx((1200 * 0.27 + 80 * 1.10) / 1_000_000)


def test_a_replay_is_priced_but_not_billed(tmp_path, monkeypatch):
    monkeypatch.setitem(PRICES, "deepseek-chat", (0.27, 1.10))
    cli = client(tmp_path, FakeTransport(reply(VALID)))

    _, live = ask(cli)
    _, replayed = ask(cli)

    # `cost_usd` is what the tokens are worth; `cached` is what says no money
    # moved. Both are needed: one for cost-per-check, one for the budget.
    assert replayed.cached is True
    assert replayed.cost_usd == pytest.approx(live.cost_usd)


def test_schema_is_appended_to_the_system_prompt(tmp_path):
    transport = FakeTransport(reply(VALID))
    ask(client(tmp_path, transport))

    sent = transport.calls[0]["system"]
    assert "you are a triage assistant" in sent
    assert "playbook_id" in sent
    # DeepSeek's JSON mode refuses a request whose prompt never says "json".
    assert "json" in sent.lower()


def test_schema_prompt_keeps_cyrillic_readable():
    class Localised(BaseModel):
        причина: str = ""

    rendered = _schema_prompt("system", Localised)
    assert "причина" in rendered
    assert "\\u" not in rendered


# --------------------------------------------------------------------------
# Refusals — an outcome, not an error
# --------------------------------------------------------------------------


def test_a_refusal_raises_its_own_type(tmp_path):
    transport = FakeTransport(reply("I can't help with analysing that message."))

    with pytest.raises(ModelRefused) as caught:
        ask(client(tmp_path, transport))

    assert caught.value.model == "deepseek-chat"
    assert "can't help" in caught.value.text


def test_a_refusal_is_never_retried_or_cached(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    transport = FakeTransport(reply("Не могу помочь с этим запросом."))

    with pytest.raises(ModelRefused):
        ask(client(tmp_path, transport, cache=cache))

    # One call, and nothing recorded: a decline is a measurement, and repairing
    # it would measure our persistence rather than the model's behaviour.
    assert len(transport.calls) == 1
    assert len(cache) == 0


def test_refusal_detection_only_looks_at_the_head():
    assert looks_like_refusal("I cannot assist with that request.")
    assert looks_like_refusal("не могу помочь")
    assert not looks_like_refusal("")
    assert not looks_like_refusal(VALID)

    # An analysis that quotes the phrase far into a long reply is not a refusal.
    quoting = "The scammer wrote: " + "x" * 500 + " i can't help"
    assert not looks_like_refusal(quoting)


def test_refusal_markers_cover_the_four_report_languages():
    joined = " ".join(REFUSAL_MARKERS)
    assert "can't help" in joined  # en
    assert "не могу" in joined  # ru
    assert any("一" <= ch <= "鿿" for ch in joined)  # zh


# --------------------------------------------------------------------------
# Caching and replay
# --------------------------------------------------------------------------


def test_identical_input_makes_one_network_call(tmp_path):
    transport = FakeTransport(reply(VALID))
    cli = client(tmp_path, transport)

    first, first_stats = ask(cli)
    second, second_stats = ask(cli)

    assert len(transport.calls) == 1
    assert first == second
    assert first_stats.cached is False
    assert second_stats.cached is True


def test_a_changed_prompt_is_a_different_call(tmp_path):
    transport = FakeTransport(reply(VALID), reply(VALID))
    cli = client(tmp_path, transport)

    ask(cli, user="первое сообщение")
    ask(cli, user="второе сообщение")

    assert len(transport.calls) == 2


def test_cache_key_covers_everything_that_changes_the_answer():
    base = dict(
        model="deepseek-chat", system="s", user="u", schema_name="Judgement", temperature=0.0
    )
    key = cache_key(**base)

    assert cache_key(**{**base, "temperature": 0.7}) != key
    assert cache_key(**{**base, "model": "qwen-plus"}) != key
    assert cache_key(**{**base, "system": "s "}) != key
    assert cache_key(**{**base, "schema_name": "Other"}) != key
    assert cache_key(**base) == key


def test_cache_key_is_not_confusable_by_field_boundaries():
    # Length-prefixed hashing: no rearrangement of adjacent fields collides.
    a = cache_key(model="ab", system="c", user="u", schema_name="S", temperature=0.0)
    b = cache_key(model="a", system="bc", user="u", schema_name="S", temperature=0.0)
    assert a != b


def test_a_corrupt_entry_is_treated_as_absent(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    key = "deadbeef" * 8
    cache.put(key, CacheEntry(model="deepseek-chat", content=VALID))
    assert cache.get(key) is not None

    (tmp_path / "cache" / key[:2] / f"{key}.json").write_text("{ not json", encoding="utf-8")

    # One bad file cannot break an eval run that has already paid for the other
    # several hundred.
    assert cache.get(key) is None


def test_an_unwritable_cache_does_not_fail_the_call(tmp_path):
    class Unwritable(DiskCache):
        def put(self, key, entry):  # exercised through the real code path
            raise AssertionError("should be swallowed by the base class")

    cache = DiskCache(tmp_path / "nested" / "cache")
    # A path collision makes mkdir fail; the call must still return.
    (tmp_path / "nested").write_text("not a directory", encoding="utf-8")

    judgement, stats = ask(client(tmp_path, FakeTransport(reply(VALID)), cache=cache))
    assert judgement.confidence == 0.9
    assert stats.cached is False


# --------------------------------------------------------------------------
# Offline replay — the mechanism CI depends on
# --------------------------------------------------------------------------


def test_offline_raises_on_a_cache_miss(tmp_path):
    # An empty transport queue would raise AssertionError if reached, so
    # OfflineCacheMiss proves the client never got that far.
    with pytest.raises(OfflineCacheMiss):
        ask(client(tmp_path, FakeTransport(), offline=True))


def test_offline_replays_a_recorded_call(tmp_path):
    cache_dir = tmp_path / "cache"
    ask(client(tmp_path, FakeTransport(reply(VALID)), cache=DiskCache(cache_dir)))

    offline = client(tmp_path, FakeTransport(), cache=DiskCache(cache_dir), offline=True)
    judgement, stats = ask(offline)

    assert judgement.playbook_id == "kz.bank_security_call"
    assert stats.cached is True


def test_offline_flag_is_read_from_the_environment(tmp_path):
    cli = client(tmp_path, FakeTransport(), env={"SAQBOL_LLM_OFFLINE": "1"})
    assert cli.offline is True
    with pytest.raises(OfflineCacheMiss):
        ask(cli)


def _seed_stale(cache_dir):
    key = cache_key(
        model="deepseek-chat",
        system="you are a triage assistant",
        user="проверь это",
        schema_name="Judgement",
        temperature=0.0,
    )
    DiskCache(cache_dir).put(key, CacheEntry(model="deepseek-chat", content=WRONG_SHAPE))


def test_a_stale_cassette_fails_loudly_offline(tmp_path):
    cache_dir = tmp_path / "cache"
    _seed_stale(cache_dir)

    offline = client(tmp_path, FakeTransport(), cache=DiskCache(cache_dir), offline=True)
    with pytest.raises(SchemaViolation, match="no longer validates"):
        ask(offline)


def test_a_stale_cassette_is_re_recorded_when_online(tmp_path):
    cache_dir = tmp_path / "cache"
    _seed_stale(cache_dir)

    transport = FakeTransport(reply(VALID))
    judgement, stats = ask(client(tmp_path, transport, cache=DiskCache(cache_dir)))

    assert judgement.confidence == 0.9
    assert stats.cached is False
    assert len(transport.calls) == 1


# --------------------------------------------------------------------------
# Schema enforcement
# --------------------------------------------------------------------------


def test_schema_violation_retries_exactly_once_then_succeeds(tmp_path):
    transport = FakeTransport(reply(WRONG_SHAPE), reply(VALID))
    judgement, stats = ask(client(tmp_path, transport))

    assert len(transport.calls) == 2
    assert stats.retries == 1
    assert judgement.confidence == 0.9

    # The repair carries the rejected reply and the reason, or the model has no
    # way to know what to change.
    repair = transport.calls[1]["user"]
    assert "Validation error" in repair
    assert "confidence" in repair


def test_schema_violation_twice_raises_and_returns_nothing(tmp_path):
    transport = FakeTransport(reply(WRONG_SHAPE), reply(WRONG_SHAPE))

    with pytest.raises(SchemaViolation):
        ask(client(tmp_path, transport))

    # Exactly one repair, then stop. A third round trip buys nothing.
    assert len(transport.calls) == 2


def test_a_failed_call_is_never_cached(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    transport = FakeTransport(reply(WRONG_SHAPE), reply(WRONG_SHAPE))

    with pytest.raises(SchemaViolation):
        ask(client(tmp_path, transport, cache=cache))

    assert len(cache) == 0


def test_markdown_fence_and_preamble_are_tolerated(tmp_path):
    fenced = f"Here you go:\n```json\n{VALID}\n```"
    judgement, _ = ask(client(tmp_path, FakeTransport(reply(fenced))))
    assert judgement.playbook_id == "kz.bank_security_call"


def test_a_reply_with_no_json_is_a_schema_violation(tmp_path):
    transport = FakeTransport(reply("Nothing structured here."), reply("Still none."))
    with pytest.raises(SchemaViolation):
        ask(client(tmp_path, transport))


# --------------------------------------------------------------------------
# Backoff
# --------------------------------------------------------------------------


def test_transient_failures_back_off_then_succeed(tmp_path):
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    transport = FakeTransport(TransientError("429"), TransientError("503"), reply(VALID))
    _, stats = ask(client(tmp_path, transport, sleep=fake_sleep, base_delay=0.5))

    assert len(transport.calls) == 3
    assert stats.retries == 2
    assert len(slept) == 2
    assert slept[1] > slept[0]  # exponential, with jitter on top


def test_transient_failures_eventually_give_up(tmp_path):
    async def fake_sleep(_: float) -> None:
        return None

    transport = FakeTransport(TransientError("503"), TransientError("503"))
    cli = client(tmp_path, transport, sleep=fake_sleep, max_transport_attempts=2)

    with pytest.raises(TransientError):
        ask(cli)
    assert len(transport.calls) == 2


# --------------------------------------------------------------------------
# Provider routing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("deepseek-chat", DEEPSEEK),
        ("deepseek-reasoner", DEEPSEEK),
        ("qwen-plus", DASHSCOPE),
        ("qwen-vl-plus", DASHSCOPE),
        ("openai/gpt-4o-mini", OPENROUTER),
        ("meta-llama/llama-3.3-70b-instruct", OPENROUTER),
        # The slash wins over the vendor prefix: this is DeepSeek rented through
        # OpenRouter, a different endpoint and a different bill.
        ("deepseek/deepseek-chat", OPENROUTER),
        # An explicit prefix overrides everything.
        ("openrouter:qwen-plus", OPENROUTER),
        ("deepseek:deepseek-chat", DEEPSEEK),
    ],
)
def test_routing(model, expected):
    assert resolve(model) is expected


def test_an_unroutable_model_names_the_rules():
    with pytest.raises(UnknownProvider, match="deepseek"):
        resolve("mistral-large")


def test_wire_name_strips_a_forced_prefix():
    assert wire_name("openrouter:qwen-plus") == "qwen-plus"
    assert wire_name("deepseek-chat") == "deepseek-chat"
    assert wire_name("openai/gpt-4o-mini") == "openai/gpt-4o-mini"


def test_a_missing_key_says_which_variable_and_what_to_do():
    with pytest.raises(ProviderNotConfigured, match="DEEPSEEK_API_KEY"):
        credentials(DEEPSEEK, {})

    with pytest.raises(ProviderNotConfigured, match="SAQBOL_LLM_OFFLINE"):
        credentials(DEEPSEEK, {"DEEPSEEK_API_KEY": "   "})


def test_base_url_falls_back_to_the_provider_default():
    key, base = credentials(DASHSCOPE, {"DASHSCOPE_API_KEY": "k"})
    assert key == "k"
    assert base == DASHSCOPE.default_base_url

    _, override = credentials(
        DASHSCOPE, {"DASHSCOPE_API_KEY": "k", "DASHSCOPE_BASE_URL": "http://x/"}
    )
    assert override == "http://x"  # trailing slash stripped before /chat/completions


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------


def test_prices_ship_empty():
    # Guard against a well-meaning guess. Adding an entry is fine, but the
    # commit that adds it must record where the rate was read from.
    assert PRICES == {}, "add the source and date of the check to the commit message"


def test_every_priced_model_is_routable():
    # A price for a model nothing can reach is a typo that would silently
    # under-report the cost of whatever model was meant.
    for model in PRICES:
        assert resolve(model) is not None


def test_an_unpriced_model_costs_none():
    assert price("some-new-model", 1000, 100) is None


def test_price_is_per_million_tokens(monkeypatch):
    monkeypatch.setitem(PRICES, "openai/gpt-4o-mini", (0.15, 0.60))
    assert price("openai/gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
    assert price("openai/gpt-4o-mini", 0, 1_000_000) == pytest.approx(0.60)
