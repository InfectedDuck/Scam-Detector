"""The HTTP surface against an in-memory store: docs/02_DATA_CONTRACTS.md section 5.

Everything here is offline. No provider key is set, so the pipeline behind
`POST /api/v1/analyze` is the deterministic rules-only configuration.
"""

from __future__ import annotations

import base64
import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from saqbol.api.deps import PROVIDER_KEY_ENVS, Deps, Settings
from saqbol.api.main import create_app, decoded_image_size, seconds_until_utc_midnight
from saqbol.db.models import Check, Feedback
from saqbol.db.repo import Store, session_for

SCAM_RU = (
    "Здравствуйте, вас беспокоит служба безопасности Kaspi банка. Мошенники пытаются "
    "оформить кредит на ваше имя. Чтобы отменить операцию, срочно продиктуйте код из СМС "
    "и переведите деньги на безопасный счёт. Установите AnyDesk для проверки. "
    "Никому не говорите об этом звонке, иначе деньги пропадут."
)
BENIGN_RU = "Привет! Встретимся завтра в 15:00 у университета, принесу книги, которые обещал."

HEX32 = re.compile(r"^[0-9a-f]{32}$")
STATS_KEYS = {"total_checks", "unique_users", "scam_share", "days", "updated_at"}
PRIVATE_PLAYBOOK_FIELDS = {"expected_indicators", "retrieval_phrases"}

#: 48 characters, clears the hashing module's minimum and is not a placeholder.
TEST_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"
API_ENVS = (
    "DATABASE_URL",
    "MAX_TEXT_CHARS",
    "MAX_IMAGE_BYTES",
    "DAILY_CHECK_LIMIT",
    "TRUST_PROXY",
    "CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTOR_HASH_SECRET", TEST_SECRET)
    for name in (*PROVIDER_KEY_ENVS, *API_ENVS):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def store() -> Store:
    return Store.in_memory()


def make_client(store: Store) -> TestClient:
    """A client over a fresh app. Settings come from the environment as they would in production."""
    return TestClient(create_app(Deps(store=store)))


@pytest.fixture
def client(store: Store):
    with make_client(store) as c:
        yield c


def analyze(client: TestClient, text: str | None, *, headers: dict | None = None, **body):
    payload = {"text": text, "surface": "web", **body}
    return client.post("/api/v1/analyze", json=payload, headers=headers)


def rows(store: Store, model):
    with session_for(store) as session:
        return session.execute(select(model)).scalars().all()


# --------------------------------------------------------------- analyze


def test_scam_text_gets_a_verdict_with_evidence(client: TestClient) -> None:
    response = analyze(client, SCAM_RU, lang_hint="ru")
    assert response.status_code == 200
    body = response.json()
    assert body["band"] in {"scam", "suspicious"}
    assert body["evidence"]
    assert HEX32.match(body["check_id"])
    assert body["playbook_id"] == "kz.bank_security_call"
    assert body["language"] == "ru"
    # The web highlights spans against this string, so every offset must land.
    normalized = body["normalized_text"]
    for span in body["evidence"]:
        assert normalized[span["start"] : span["end"]] == span["text"]


def test_benign_text_is_likely_safe(client: TestClient) -> None:
    body = analyze(client, BENIGN_RU).json()
    assert body["band"] == "likely_safe"
    assert body["evidence"] == []
    assert body["normalized_text"]


def test_text_over_the_limit_is_413(client: TestClient) -> None:
    response = analyze(client, "а" * 8001)
    assert response.status_code == 413
    assert response.json() == {"error": "too_large"}
    assert analyze(client, "а" * 8000).status_code == 200


def test_image_over_the_limit_is_413(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_IMAGE_BYTES", "300")
    # 400 bytes of zeros encodes to 536 base64 characters; a data URL prefix must not matter.
    image = "data:image/png;base64," + "A" * 532 + "AA=="
    assert decoded_image_size(image) == 400
    with make_client(store) as client:
        response = analyze(client, SCAM_RU, image_b64=image)
        assert response.status_code == 413
        assert response.json() == {"error": "too_large"}


def test_image_only_is_refused_not_faked(client: TestClient, store: Store) -> None:
    response = analyze(client, None, image_b64="aGVsbG8=")
    assert response.status_code == 422
    assert response.json() == {"error": "image_not_supported"}
    assert rows(store, Check) == []


# ------------------------------------------------------------ screenshots

#: A JPEG header on a recognisable payload, so a test can prove the bytes went nowhere.
IMAGE_BYTES = b"\xff\xd8\xff\xe0" + b"SAQBOL-SCREENSHOT-BYTES-" * 8
IMAGE_B64 = base64.b64encode(IMAGE_BYTES).decode("ascii")
TRANSCRIPT = "[Kaspi · +7 700 000 00 00]\n> " + SCAM_RU


class FakePerceive:
    """Scripted screenshot reader. Records what it saw so a test can check it."""

    def __init__(self, reply: str | Exception = TRANSCRIPT) -> None:
        self.reply = reply
        self.calls: list[tuple[bytes, object]] = []

    async def __call__(self, image: bytes, *, locale) -> str:
        self.calls.append((image, locale))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def vision_client(store: Store, perceive: FakePerceive) -> TestClient:
    return TestClient(create_app(Deps(store=store, perceive=perceive)))


def test_screenshot_is_read_then_analysed_as_text(store: Store) -> None:
    reader = FakePerceive()
    with vision_client(store, reader) as client:
        response = analyze(client, None, image_b64=IMAGE_B64, lang_hint="ru")
    assert response.status_code == 200, response.text
    body = response.json()

    # The reader got the decoded bytes and the caller's language, once.
    assert reader.calls == [(IMAGE_BYTES, "ru")]
    # The transcript is the text from here on: scored, offset-indexed and stored.
    assert body["band"] == "scam"
    assert SCAM_RU[:40] in body["normalized_text"]
    assert all(
        body["normalized_text"][span["start"] : span["end"]] == span["text"]
        for span in body["evidence"]
    )
    (check,) = rows(store, Check)
    assert check.input_type == "image"
    assert IMAGE_B64 not in check.text_scrubbed
    assert "SAQBOL-SCREENSHOT" not in check.text_scrubbed


def test_screenshot_accepts_a_data_url_and_keeps_typed_text_as_context(store: Store) -> None:
    reader = FakePerceive()
    with vision_client(store, reader) as client:
        response = analyze(
            client, "Это мне пришло сегодня", image_b64="data:image/jpeg;base64," + IMAGE_B64
        )
    assert response.status_code == 200, response.text
    assert reader.calls[0][0] == IMAGE_BYTES
    normalized = response.json()["normalized_text"]
    assert normalized.index(SCAM_RU[:20]) < normalized.index("Это мне пришло сегодня")


def test_non_image_payload_is_refused_before_a_check_is_spent(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DAILY_CHECK_LIMIT", "1")
    reader = FakePerceive()
    with vision_client(store, reader) as client:
        for payload in ("aGVsbG8=", "not base64!!", base64.b64encode(b"%PDF-1.4").decode()):
            response = analyze(client, None, image_b64=payload)
            assert response.status_code == 422, payload
            assert response.json() == {"error": "invalid_image"}
        assert reader.calls == []
        # The limit was never touched by the refusals: one real check still goes through.
        assert analyze(client, None, image_b64=IMAGE_B64).status_code == 200


def test_screenshot_spends_the_daily_check_before_the_vision_call(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DAILY_CHECK_LIMIT", "1")
    reader = FakePerceive()
    with vision_client(store, reader) as client:
        assert analyze(client, None, image_b64=IMAGE_B64).status_code == 200
        response = analyze(client, None, image_b64=IMAGE_B64)
    assert response.status_code == 429
    assert len(reader.calls) == 1


def test_unreadable_screenshot_is_502_and_records_nothing(store: Store) -> None:
    with vision_client(store, FakePerceive(RuntimeError("provider down"))) as client:
        response = analyze(client, None, image_b64=IMAGE_B64)
    assert response.status_code == 502
    assert response.json() == {"error": "image_unreadable"}
    assert rows(store, Check) == []


def test_screenshot_with_no_text_is_422_unless_text_came_with_it(store: Store) -> None:
    with vision_client(store, FakePerceive("")) as client:
        response = analyze(client, None, image_b64=IMAGE_B64)
        assert response.status_code == 422
        assert response.json() == {"error": "image_no_text"}
        # Typed text alongside an empty screenshot is still a check on that text.
        response = analyze(client, SCAM_RU, image_b64=IMAGE_B64)
        assert response.status_code == 200
        assert response.json()["band"] == "scam"
    (check,) = rows(store, Check)
    assert check.input_type == "image"


def test_screenshot_bytes_never_reach_a_log_line(store: Store, caplog) -> None:
    with caplog.at_level(logging.DEBUG), vision_client(store, FakePerceive()) as client:
        analyze(client, None, image_b64=IMAGE_B64)
        analyze(client, None, image_b64=IMAGE_B64.replace("SAQBOL", "XXXXXX"))
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "SAQBOL-SCREENSHOT" not in joined
    assert IMAGE_B64[:24] not in joined


def test_empty_and_invalid_bodies_are_422_with_an_error_key(client: TestClient) -> None:
    assert analyze(client, "   ").json() == {"error": "empty_input"}
    assert analyze(client, None).status_code == 422
    response = client.post("/api/v1/analyze", json={"text": 123})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_input"
    assert "detail" in response.json()


def test_daily_limit_is_enforced_per_actor(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_CHECK_LIMIT", "2")
    with make_client(store) as client:
        assert analyze(client, BENIGN_RU).status_code == 200
        assert analyze(client, BENIGN_RU).status_code == 200
        response = analyze(client, BENIGN_RU)
    assert response.status_code == 429
    body = response.json()
    assert body["error"] == "rate_limited"
    assert isinstance(body["retry_after"], int)
    assert 1 <= body["retry_after"] <= 24 * 3600
    assert response.headers["retry-after"] == str(body["retry_after"])
    # A rejected request is not a check.
    assert len(rows(store, Check)) == 2


def test_forwarded_header_is_ignored_unless_the_proxy_is_trusted(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DAILY_CHECK_LIMIT", "1")
    with make_client(store) as client:
        first = analyze(client, BENIGN_RU, headers={"X-Forwarded-For": "203.0.113.1"})
        second = analyze(client, BENIGN_RU, headers={"X-Forwarded-For": "203.0.113.2"})
    assert first.status_code == 200
    # Same socket peer, so the same bucket: a client cannot pick its own limit.
    assert second.status_code == 429


def test_forwarded_header_identifies_the_client_behind_a_trusted_proxy(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DAILY_CHECK_LIMIT", "1")
    monkeypatch.setenv("TRUST_PROXY", "1")
    with make_client(store) as client:
        one = analyze(client, BENIGN_RU, headers={"X-Forwarded-For": "203.0.113.1, 10.0.0.1"})
        two = analyze(client, BENIGN_RU, headers={"X-Forwarded-For": "203.0.113.2, 10.0.0.1"})
        again = analyze(client, BENIGN_RU, headers={"X-Forwarded-For": "203.0.113.1, 10.0.0.1"})
    assert (one.status_code, two.status_code, again.status_code) == (200, 200, 429)
    assert len({c.actor_hash for c in rows(store, Check)}) == 2


def test_surface_header_and_consent_are_recorded(client: TestClient, store: Store) -> None:
    # The body's own surface is client-controlled; the header decides.
    web = analyze(
        client,
        SCAM_RU,
        consent_dataset=True,
        surface="telegram",
        headers={"X-Saqbol-Surface": "web"},
    )
    api = analyze(client, BENIGN_RU)
    assert web.status_code == api.status_code == 200
    by_id = {c.id.hex: c for c in rows(store, Check)}
    assert by_id[web.json()["check_id"]].surface == "web"
    assert by_id[web.json()["check_id"]].consent_dataset is True
    assert by_id[api.json()["check_id"]].surface == "api"
    assert by_id[api.json()["check_id"]].consent_dataset is False
    assert all(c.input_type == "text" for c in by_id.values())


def test_logs_carry_no_text_and_no_address(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="saqbol.api")
    response = analyze(client, SCAM_RU, headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records if record.name == "saqbol.api"]
    assert any(response.json()["check_id"] in m for m in messages)
    joined = "\n".join(messages)
    for forbidden in ("безопасности", "Kaspi", "203.0.113.7", "testclient"):
        assert forbidden not in joined


# -------------------------------------------------------------- feedback


def test_feedback_is_stored_then_unknown_ids_are_404(client: TestClient, store: Store) -> None:
    check_id = analyze(client, SCAM_RU).json()["check_id"]
    response = client.post(
        "/api/v1/feedback",
        json={"check_id": check_id, "was_correct": False, "comment": "it was my bank"},
    )
    assert response.status_code == 204
    assert response.content == b""

    feedback = rows(store, Feedback)
    assert len(feedback) == 1
    assert feedback[0].check_id.hex == check_id
    assert feedback[0].was_correct is False
    assert feedback[0].comment == "it was my bank"

    for bogus in ("0" * 32, "not-an-id"):
        response = client.post("/api/v1/feedback", json={"check_id": bogus, "was_correct": None})
        assert response.status_code == 404
        assert response.json() == {"error": "unknown_check"}
    assert len(rows(store, Feedback)) == 1


# ----------------------------------------------------------------- stats


def test_stats_has_the_contract_keys_and_counts_live(client: TestClient) -> None:
    for text in (SCAM_RU, SCAM_RU, BENIGN_RU):
        assert analyze(client, text).status_code == 200
    body = client.get("/api/v1/stats").json()
    assert set(body) == STATS_KEYS
    assert body["total_checks"] == 3
    assert body["unique_users"] == 1
    assert isinstance(body["scam_share"], float)
    assert 0.0 <= body["scam_share"] <= 1.0
    assert len(body["days"]) == 1
    assert body["days"][0]["checks"] == 3
    assert body["updated_at"].endswith("+00:00")


# ------------------------------------------------------------- playbooks


def test_playbook_library_lists_all_thirteen_without_internals(client: TestClient) -> None:
    body = client.get("/api/v1/playbooks").json()
    assert len(body) == 13
    assert [p["id"] for p in body] == sorted(p["id"] for p in body)
    for playbook in body:
        assert not PRIVATE_PLAYBOOK_FIELDS & set(playbook)
        assert playbook["name"]["ru"]
        assert playbook["summary"]["ru"]
        assert len(playbook["red_flags"]["ru"]) >= 2
        assert playbook["action"]["key"].startswith("action.")
        assert playbook["action"]["text"]["ru"]
        assert playbook["hotlines"] and all(
            {"name", "number"} <= set(h) for h in playbook["hotlines"]
        )
        assert playbook["sources"]
        assert None not in playbook["name"].values()


def test_playbook_detail_and_unknown_id(client: TestClient) -> None:
    response = client.get("/api/v1/playbooks/kz.bank_security_call")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "kz.bank_security_call"
    assert body["region"] == "KZ"
    assert body["hotline"]
    assert not PRIVATE_PLAYBOOK_FIELDS & set(body)

    response = client.get("/api/v1/playbooks/kz.nonsense")
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_playbook"}


# --------------------------------------------------------------- healthz


def test_healthz_reports_db_and_no_llm(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "db": True, "llm": False, "vision": False}


def test_healthz_sees_a_provider_key_without_calling_anyone(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "not-a-real-key")
    with make_client(store) as client:
        assert client.get("/healthz").json() == {
            "ok": True,
            "db": True,
            "llm": True,
            "vision": True,
        }


# ------------------------------------------------------------ app wiring


def test_cors_is_off_by_default_and_on_from_env(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    preflight = {"Origin": "https://saqbol.kz", "Access-Control-Request-Method": "POST"}
    with make_client(store) as client:
        response = client.options("/api/v1/analyze", headers=preflight)
        assert "access-control-allow-origin" not in response.headers

    monkeypatch.setenv("CORS_ORIGINS", "https://saqbol.kz, http://localhost:3000")
    with make_client(store) as client:
        response = client.options("/api/v1/analyze", headers=preflight)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://saqbol.kz"


def test_settings_and_helpers() -> None:
    assert Settings.from_env() == Settings()
    assert Settings.from_env().daily_check_limit == 10
    assert Settings.from_env().max_text_chars == 8000
    assert Settings.from_env().max_image_bytes == 5 * 1024 * 1024
    assert 1 <= seconds_until_utc_midnight() <= 24 * 3600
    assert decoded_image_size("aGVsbG8=") == len(b"hello")
    assert decoded_image_size("aGVs\nbG8=") == len(b"hello")
    assert decoded_image_size("") == 0
