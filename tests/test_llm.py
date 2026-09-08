"""T111 — LLM client: caching, schema enforcement, retries, refusal detection.

Every test injects a fake transport, so the suite exercises the real client
logic with no network and no API key. The two behaviours the task specifies are
asserted directly: the same input twice makes one network call, and a schema
violation triggers exactly one retry before failing cleanly.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from saqbol.core.llm import (
    MODELS,
    LLMClient,
    LLMError,
    _extract_json,
    looks_like_refusal,
)


class Verdict(BaseModel):
    playbook_id: str
    confidence: float


def reply(content: str, *, prompt_tokens: int = 100, completion_tokens: int = 20) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class FakeTransport:
    """Records every request and returns queued responses in order."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, url, headers, body):
        self.requests.append({"url": url, "headers": headers, "body": body})
        if not self.responses:
            raise AssertionError("transport called more times than the test queued")
        return self.responses.pop(0)

    @property
    def calls(self) -> int:
        return len(self.requests)


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")


def client(tmp_path, transport) -> LLMClient:
    return LLMClient(cache_dir=tmp_path / "cache", transport=transport, sleep=lambda _s: None)


MESSAGES = [{"role": "user", "content": "Это мошенничество?"}]


class TestBasicCompletion:
    def test_returns_text(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("Похоже на мошенничество."))])
        response = client(tmp_path, transport).complete(MESSAGES)
        assert response.text == "Похоже на мошенничество."
        assert response.cached is False
        assert transport.calls == 1

    def test_missing_api_key_is_a_clean_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        transport = FakeTransport([])
        with pytest.raises(LLMError) as err:
            client(tmp_path, transport).complete(MESSAGES)
        assert err.value.code == "no_api_key"
        assert transport.calls == 0

    def test_unknown_model_rejected(self, tmp_path, api_key):
        with pytest.raises(LLMError) as err:
            client(tmp_path, FakeTransport([])).complete(MESSAGES, model="not-a-model")
        assert err.value.code == "unknown_model"

    def test_usage_is_recorded(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("ok", prompt_tokens=321, completion_tokens=45))])
        response = client(tmp_path, transport).complete(MESSAGES)
        assert response.prompt_tokens == 321
        assert response.completion_tokens == 45

    def test_cost_is_none_when_the_price_is_unverified(self, tmp_path, api_key):
        """A wrong price in a published cost table is worse than an absent one,
        so unknown stays unknown."""
        assert MODELS["deepseek-v3"].usd_per_million_in is None
        transport = FakeTransport([(200, reply("ok"))])
        assert client(tmp_path, transport).complete(MESSAGES).cost_usd is None


class TestCache:
    def test_same_input_twice_makes_one_call(self, tmp_path, api_key):
        """The requirement from T109's sibling task, asserted literally."""
        transport = FakeTransport([(200, reply("одинаковый ответ"))])
        c = client(tmp_path, transport)
        first = c.complete(MESSAGES)
        second = c.complete(MESSAGES)
        assert transport.calls == 1
        assert first.text == second.text
        assert first.cached is False
        assert second.cached is True

    def test_cache_survives_a_new_client(self, tmp_path, api_key):
        """A leaderboard rerun in a fresh process must not pay again."""
        transport = FakeTransport([(200, reply("ответ"))])
        client(tmp_path, transport).complete(MESSAGES)
        fresh = FakeTransport([])
        again = client(tmp_path, fresh).complete(MESSAGES)
        assert again.cached is True
        assert fresh.calls == 0

    def test_different_temperature_is_a_different_key(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("a")), (200, reply("b"))])
        c = client(tmp_path, transport)
        c.complete(MESSAGES, temperature=0.0)
        c.complete(MESSAGES, temperature=0.7)
        assert transport.calls == 2

    def test_different_model_is_a_different_key(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("a")), (200, reply("b"))])
        c = client(tmp_path, transport)
        c.complete(MESSAGES, model="deepseek-v3")
        c.complete(MESSAGES, model="gpt-4o-mini")
        assert transport.calls == 2

    def test_cache_can_be_bypassed(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("a")), (200, reply("b"))])
        c = client(tmp_path, transport)
        c.complete(MESSAGES)
        c.complete(MESSAGES, use_cache=False)
        assert transport.calls == 2

    def test_unwritable_cache_does_not_fail_the_call(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("ok"))])
        c = LLMClient(cache_dir=tmp_path / "x", transport=transport, sleep=lambda _s: None)
        c._cache_path = lambda key: tmp_path / "nope" / "\0bad"
        assert c.complete(MESSAGES).text == "ok"


class TestStructuredOutput:
    def test_valid_json_is_parsed(self, tmp_path, api_key):
        transport = FakeTransport(
            [(200, reply('{"playbook_id": "kz.apk_install", "confidence": 0.9}'))]
        )
        response = client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        assert response.parsed.playbook_id == "kz.apk_install"
        assert response.parsed.confidence == 0.9

    def test_fenced_json_is_tolerated(self, tmp_path, api_key):
        transport = FakeTransport(
            [(200, reply('```json\n{"playbook_id": "kz.fake_store", "confidence": 0.4}\n```'))]
        )
        response = client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        assert response.parsed.playbook_id == "kz.fake_store"

    def test_prose_around_the_object_is_tolerated(self, tmp_path, api_key):
        transport = FakeTransport(
            [
                (
                    200,
                    reply(
                        'Вот результат: {"playbook_id": "kz.fake_store", "confidence": 0.4} готово'
                    ),
                )
            ]
        )
        assert client(tmp_path, transport).complete(MESSAGES, schema=Verdict).parsed

    def test_violation_retries_exactly_once_then_fails(self, tmp_path, api_key):
        """Two bad answers must not become an unbounded correction loop."""
        transport = FakeTransport([(200, reply("не json")), (200, reply("тоже не json"))])
        with pytest.raises(LLMError) as err:
            client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        assert err.value.code == "schema_violation"
        assert transport.calls == 2

    def test_retry_can_succeed(self, tmp_path, api_key):
        transport = FakeTransport(
            [
                (200, reply("извините, не json")),
                (200, reply('{"playbook_id": "kz.delivery_link", "confidence": 0.7}')),
            ]
        )
        response = client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        assert response.parsed.playbook_id == "kz.delivery_link"
        assert response.attempts == 2

    def test_retry_shows_the_model_its_error(self, tmp_path, api_key):
        transport = FakeTransport(
            [
                (200, reply("nope")),
                (200, reply('{"playbook_id": "kz.fake_store", "confidence": 0.1}')),
            ]
        )
        client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        follow_up = transport.requests[1]["body"]["messages"]
        assert any("did not match the required JSON schema" in m["content"] for m in follow_up)

    def test_schema_is_described_in_prompt_when_unsupported(self, tmp_path, api_key):
        transport = FakeTransport(
            [(200, reply('{"playbook_id": "kz.apk_install", "confidence": 0.5}'))]
        )
        client(tmp_path, transport).complete(MESSAGES, schema=Verdict, model="deepseek-v3")
        body = transport.requests[0]["body"]
        assert body["response_format"] == {"type": "json_object"}
        assert any("JSON Schema" in m["content"] for m in body["messages"])

    def test_strict_schema_used_where_supported(self, tmp_path, api_key):
        transport = FakeTransport(
            [(200, reply('{"playbook_id": "kz.apk_install", "confidence": 0.5}'))]
        )
        client(tmp_path, transport).complete(MESSAGES, schema=Verdict, model="gpt-4o-mini")
        body = transport.requests[0]["body"]
        assert body["response_format"]["type"] == "json_schema"


class TestRefusals:
    @pytest.mark.parametrize(
        "text",
        [
            "I can't help with that request.",
            "I cannot assist with creating scam messages.",
            "Извините, я не могу помочь с этим запросом.",
        ],
    )
    def test_detected(self, text):
        assert looks_like_refusal(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Это мошенничество. Не сообщайте код.",
            '{"playbook_id": "kz.apk_install", "confidence": 0.9}',
            "",
        ],
    )
    def test_not_triggered_by_an_answer(self, text):
        assert not looks_like_refusal(text)

    def test_quoted_phrase_late_in_an_answer_is_not_a_refusal(self):
        """The marker is checked near the start, so an analysis that quotes the
        phrase is not miscounted."""
        analysis = "Это мошенничество. " + "Подробный разбор. " * 30 + "I can't help"
        assert not looks_like_refusal(analysis)

    def test_refusal_is_an_outcome_not_an_exception(self, tmp_path, api_key):
        """Refusal rate is a leaderboard column, so it must survive as data."""
        transport = FakeTransport([(200, reply("I can't help with that request."))])
        response = client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        assert response.refused is True
        assert response.parsed is None

    def test_refusal_is_not_retried(self, tmp_path, api_key):
        transport = FakeTransport([(200, reply("I cannot assist with that."))])
        client(tmp_path, transport).complete(MESSAGES, schema=Verdict)
        assert transport.calls == 1


class TestRetriesAndErrors:
    def test_transient_status_is_retried(self, tmp_path, api_key):
        transport = FakeTransport(
            [(503, {"error": {"message": "upstream"}}), (200, reply("recovered"))]
        )
        assert client(tmp_path, transport).complete(MESSAGES).text == "recovered"
        assert transport.calls == 2

    def test_retries_are_bounded(self, tmp_path, api_key):
        transport = FakeTransport([(500, {"error": {"message": "boom"}})] * 3)
        with pytest.raises(LLMError) as err:
            client(tmp_path, transport).complete(MESSAGES)
        assert err.value.code == "provider_error"
        assert transport.calls == 3

    def test_auth_failure_is_not_retried(self, tmp_path, api_key):
        transport = FakeTransport([(401, {"error": {"message": "bad key"}})])
        with pytest.raises(LLMError) as err:
            client(tmp_path, transport).complete(MESSAGES)
        assert err.value.code == "auth_failed"
        assert transport.calls == 1

    def test_malformed_response_is_a_clean_error(self, tmp_path, api_key):
        transport = FakeTransport([(200, {"choices": []})])
        with pytest.raises(LLMError) as err:
            client(tmp_path, transport).complete(MESSAGES)
        assert err.value.code == "bad_response"


class TestJsonExtraction:
    def test_bare_object(self):
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_fence(self):
        assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_no_object_raises(self):
        with pytest.raises(ValueError, match="no JSON object"):
            _extract_json("совсем не json")


def test_every_model_maps_to_a_real_provider():
    from saqbol.core.llm import PROVIDERS

    for key, spec in MODELS.items():
        assert spec.provider in PROVIDERS, key
