"""Bot tests. No token, no network, no database.

Telegram is replaced at the transport seam: `FakeSession` subclasses aiogram's
`BaseSession` and records the API calls the bot tries to make instead of sending
them. Everything above that seam — filters, routing, middleware, the handlers —
is the real aiogram machinery, so these tests exercise the dispatcher rather
than a hand-rolled imitation of it.

`stream_content` raises rather than returning bytes. Downloading a file is the
one thing the size caps exist to prevent, so any test that provokes a download
fails loudly instead of quietly passing.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    MessageOriginChannel,
    MessageOriginUser,
    PhotoSize,
    Update,
    User,
    Voice,
)

from saqbol.bot.actors import actor_hash, chat_key, short_ref
from saqbol.bot.cards import format_card
from saqbol.bot.config import BotConfig
from saqbol.bot.deps import (
    Card,
    Deps,
    adapt_analyze,
    build_deps,
    stub_analyze,
    stub_render_card,
)
from saqbol.bot.main import build_dispatcher
from saqbol.bot.storage import BotStore
from saqbol.core.types import Lang, Verdict

#: Distinctive so a substring search for it in a log file means something.
USER_ID = 987654321
#: In a private chat Telegram uses the same integer for the chat.
CHAT_ID = USER_ID
SECRET = "unit-test-secret-not-a-real-one"
#: Structurally valid, deliberately not a real credential.
TOKEN = "42:TESTTOKEN"

_ids = itertools.count(1)


# --------------------------------------------------------------- transport


class FakeSession(BaseSession):
    """Records outgoing Bot API calls. Opens no socket."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.calls),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
            )
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ):
        msg = f"the bot must not download anything: {url}"
        raise AssertionError(msg)
        yield b""  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        return None

    @property
    def sent(self) -> list[SendMessage]:
        return [call for call in self.calls if isinstance(call, SendMessage)]

    @property
    def texts(self) -> list[str]:
        return [call.text for call in self.sent]


class Clock:
    """Injected `Deps.now`, so day rollover and thread windows are testable."""

    def __init__(self, start: datetime) -> None:
        self.moment = start

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


@dataclass
class RecordingAnalyzer:
    """Stands in for the pipeline and remembers exactly what it was handed."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(
        self,
        text: str,
        *,
        locale: Lang,
        surface: str,
        thread: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Verdict:
        self.calls.append(
            {
                "text": text,
                "locale": locale,
                "surface": surface,
                "thread": list(thread or []),
                "metadata": dict(metadata or {}),
            }
        )
        return await stub_analyze(text, locale=locale, surface=surface, thread=thread)


@dataclass
class Harness:
    bot: Bot
    dispatcher: Dispatcher
    session: FakeSession
    deps: Deps
    store: BotStore
    clock: Clock
    analyzer: RecordingAnalyzer

    def feed(self, update: Update) -> None:
        asyncio.run(self.dispatcher.feed_update(self.bot, update))

    @property
    def texts(self) -> list[str]:
        return self.session.texts

    @property
    def last(self) -> str:
        return self.session.texts[-1]

    @property
    def transcript(self) -> str:
        return "\n".join(self.session.texts)

    def clear(self) -> None:
        self.session.calls.clear()
        self.analyzer.calls.clear()


def make_harness(
    state_path: Path,
    *,
    clock: Clock | None = None,
    **config_overrides: Any,
) -> Harness:
    config = BotConfig(
        actor_hash_secret=SECRET,
        token=TOKEN,
        state_path=state_path,
        **config_overrides,
    )
    store = BotStore(config.state_path)
    clock = clock or Clock(datetime(2026, 9, 8, 10, 0, tzinfo=UTC))
    analyzer = RecordingAnalyzer()
    deps = Deps(
        config=config,
        store=store,
        analyze=analyzer,
        render_card=stub_render_card,
        now=clock,
        analyze_is_stub=True,
        renderer_is_stub=True,
    )
    session = FakeSession()
    return Harness(
        bot=Bot(TOKEN, session=session),
        dispatcher=build_dispatcher(deps),
        session=session,
        deps=deps,
        store=store,
        clock=clock,
        analyzer=analyzer,
    )


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "bot.json"


@pytest.fixture
def bot(state_path: Path) -> Harness:
    return make_harness(state_path)


# ---------------------------------------------------------------- builders


def _user(user_id: int = USER_ID) -> User:
    return User(id=user_id, is_bot=False, first_name="Aigerim")


def message_update(
    text: str | None = None,
    *,
    user_id: int = USER_ID,
    chat_id: int = CHAT_ID,
    caption: str | None = None,
    photo: list[PhotoSize] | None = None,
    voice: Voice | None = None,
    forward_origin: Any = None,
    date: datetime | None = None,
) -> Update:
    message = Message(
        message_id=next(_ids),
        date=date or datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=_user(user_id),
        text=text,
        caption=caption,
        photo=photo,
        voice=voice,
        forward_origin=forward_origin,
    )
    return Update(update_id=next(_ids), message=message)


def callback_update(data: str, *, user_id: int = USER_ID, chat_id: int = CHAT_ID) -> Update:
    carrier = Message(
        message_id=next(_ids),
        date=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=42, is_bot=True, first_name="SaqBol"),
        text="language",
    )
    query = CallbackQuery(
        id=f"cb{next(_ids)}",
        from_user=_user(user_id),
        chat_instance="chat-instance",
        message=carrier,
        data=data,
    )
    return Update(update_id=next(_ids), callback_query=query)


def forward_from_user(*, username: str | None) -> MessageOriginUser:
    return MessageOriginUser(
        type="user",
        date=datetime(2026, 9, 8, 9, 55, tzinfo=UTC),
        sender_user=User(id=555000111, is_bot=False, first_name="Unknown", username=username),
    )


def photo(size_bytes: int) -> list[PhotoSize]:
    return [
        PhotoSize(file_id="small", file_unique_id="su", width=90, height=160, file_size=1024),
        PhotoSize(
            file_id="large", file_unique_id="lu", width=900, height=1600, file_size=size_bytes
        ),
    ]


def consent(bot: Harness) -> None:
    """Put a chat through `/start` so checks are not blocked on consent."""
    bot.feed(message_update("/start"))
    bot.clear()


# ------------------------------------------------------------------- start


def test_start_states_the_three_promises(bot: Harness) -> None:
    bot.feed(message_update("/start"))
    said = bot.transcript

    # Russian: never asks for a code, a card number or a phone number.
    assert "никогда не спрошу" in said
    assert "код из СМС" in said
    assert "номер карты" in said
    assert "номер телефона" in said
    # Russian: images are not stored.
    assert "Скриншоты не сохраняются" in said

    # Kazakh: the same three, and the same promise about screenshots.
    assert "ешқашан" in said
    assert "SMS кодын" in said
    assert "карта нөмірін" in said
    assert "телефон нөмірін" in said
    assert "Скриншоттар сақталмайды" in said


def test_start_warns_that_the_bot_never_messages_first(bot: Harness) -> None:
    """Anti-impersonation is part of the consent text, not a nicety.

    A trusted anti-fraud bot is worth impersonating.
    """
    bot.feed(message_update("/start"))
    said = bot.transcript
    assert "не пишу и не звоню первым" in said
    assert "бірінші болып жазбаймын" in said


def test_start_offers_a_language_keyboard(bot: Harness) -> None:
    bot.feed(message_update("/start"))
    markups = [call.reply_markup for call in bot.session.sent if call.reply_markup]
    assert len(markups) == 1
    keyboard = markups[0]
    assert isinstance(keyboard, InlineKeyboardMarkup)
    payloads = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert payloads == ["lang:ru", "lang:kk", "lang:en", "lang:zh"]


def test_every_reply_fits_in_one_telegram_message(bot: Harness) -> None:
    """The consent block is long. Telegram rejects anything over 4096 chars."""
    bot.feed(message_update("/start"))
    bot.feed(message_update("/help"))
    bot.feed(message_update("/privacy"))
    assert bot.texts
    assert all(len(text) <= 4096 for text in bot.texts)


def test_start_records_consent(bot: Harness, state_path: Path) -> None:
    bot.feed(message_update("/start"))
    profile = bot.store.get_profile(chat_key(SECRET, CHAT_ID))
    assert profile is not None
    assert profile.consent_at is not None
    assert state_path.exists()


# ---------------------------------------------------------------- language


def test_language_selection_switches_replies(bot: Harness) -> None:
    consent(bot)
    bot.feed(callback_update("lang:kk"))
    assert "қазақша жауап беремін" in bot.last

    bot.clear()
    bot.feed(message_update("/help"))
    assert "Не істей аламын" in bot.last


def test_language_choice_persists_across_a_restart(state_path: Path) -> None:
    first = make_harness(state_path)
    consent(first)
    first.feed(callback_update("lang:kk"))

    # A whole new process: new store, new dispatcher, same state file.
    second = make_harness(state_path)
    second.feed(message_update("/help"))
    assert "Не істей аламын" in second.last


def test_unknown_language_payload_is_ignored(bot: Harness) -> None:
    consent(bot)
    bot.feed(callback_update("lang:klingon"))
    assert bot.session.texts == []


def test_help_and_privacy_answer(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("/help"))
    assert "/privacy" in bot.last
    bot.clear()
    bot.feed(message_update("/privacy"))
    assert "PRIVACY.md" in bot.last
    assert "30" in bot.last


def test_forget_clears_the_chat(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("привет, проверь это"))
    assert bot.store.get_profile(chat_key(SECRET, CHAT_ID)) is not None

    bot.feed(message_update("/forget"))
    assert bot.store.get_profile(chat_key(SECRET, CHAT_ID)) is None


# ------------------------------------------------------------------ checks


def test_consent_is_required_before_any_check(bot: Harness) -> None:
    bot.feed(message_update("Здравствуйте, это служба безопасности банка"))
    assert bot.analyzer.calls == []
    assert "Скриншоты не сохраняются" in bot.transcript


def test_plain_text_reaches_the_pipeline(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("Назовите код из СМС"))

    assert len(bot.analyzer.calls) == 1
    call = bot.analyzer.calls[0]
    assert call["text"] == "Назовите код из СМС"
    assert call["surface"] == "telegram"
    assert call["locale"] is Lang.RU
    assert call["thread"] == ["Назовите код из СМС"]
    assert call["metadata"]["is_forward"] is False
    assert "[stub]" in bot.last


def test_forward_metadata_reaches_indicator_family_i(bot: Harness) -> None:
    consent(bot)
    bot.feed(
        message_update(
            "Мама, у меня проблема, срочно переведи деньги",
            forward_origin=forward_from_user(username=None),
        )
    )

    metadata = bot.analyzer.calls[0]["metadata"]
    assert metadata["is_forward"] is True
    assert metadata["forward_origin"] == "user"
    # The one family I key Telegram actually supplies for a forward.
    assert metadata["has_username"] is False
    assert metadata["forward_age_seconds"] == 300


def test_forward_from_a_named_account_sets_has_username(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("проверьте", forward_origin=forward_from_user(username="realbank")))
    assert bot.analyzer.calls[0]["metadata"]["has_username"] is True


def test_forward_from_a_channel_carries_the_public_handle(bot: Harness) -> None:
    consent(bot)
    origin = MessageOriginChannel(
        type="channel",
        date=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        chat=Chat(id=-100123, type="channel", title="Halyk Bonus", username="halyk_bonus_kz"),
        message_id=7,
    )
    bot.feed(message_update("розыгрыш призов", forward_origin=origin))

    metadata = bot.analyzer.calls[0]["metadata"]
    assert metadata["forward_origin"] == "channel"
    assert metadata["forward_channel_username"] == "halyk_bonus_kz"


def test_forward_metadata_omits_keys_telegram_does_not_supply(bot: Harness) -> None:
    """Family I returns nothing on an absent key and guesses on a wrong one.

    Telegram tells a bot nothing about the sender's number, the account's age or
    whether the forwarder knows them, so those keys must not be invented.
    """
    consent(bot)
    bot.feed(message_update("проверьте", forward_origin=forward_from_user(username=None)))

    metadata = bot.analyzer.calls[0]["metadata"]
    for absent in ("sender_phone", "claimed_number", "account_age_days", "is_known_contact"):
        assert absent not in metadata


def test_forward_metadata_carries_no_personal_names(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("проверьте", forward_origin=forward_from_user(username="scammer_bob")))

    metadata = bot.analyzer.calls[0]["metadata"]
    flattened = repr(metadata)
    assert "scammer_bob" not in flattened
    assert "Unknown" not in flattened
    assert "555000111" not in flattened


# ------------------------------------------------------------------ thread


def test_consecutive_messages_assemble_into_one_thread(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("Здравствуйте, вас беспокоит банк"))
    bot.clock.advance(seconds=60)
    bot.feed(message_update("Продиктуйте код, который вам пришёл"))

    assert bot.analyzer.calls[0]["thread"] == ["Здравствуйте, вас беспокоит банк"]
    assert bot.analyzer.calls[1]["thread"] == [
        "Здравствуйте, вас беспокоит банк",
        "Продиктуйте код, который вам пришёл",
    ]


def test_a_stale_message_starts_a_new_thread(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update("первое сообщение"))
    bot.clock.advance(seconds=bot.deps.config.thread_window_seconds + 60)
    bot.feed(message_update("совсем другое сообщение"))

    assert bot.analyzer.calls[1]["thread"] == ["совсем другое сообщение"]


def test_thread_is_capped(state_path: Path) -> None:
    bot = make_harness(state_path, thread_max_messages=3, daily_check_limit=50)
    consent(bot)
    for index in range(5):
        bot.feed(message_update(f"сообщение {index}"))

    assert bot.analyzer.calls[-1]["thread"] == ["сообщение 2", "сообщение 3", "сообщение 4"]


def test_a_thread_survives_a_restart(state_path: Path) -> None:
    clock = Clock(datetime(2026, 9, 8, 10, 0, tzinfo=UTC))
    first = make_harness(state_path, clock=clock)
    consent(first)
    first.feed(message_update("вас беспокоит служба безопасности"))

    second = make_harness(state_path, clock=clock)
    second.feed(message_update("назовите код"))
    assert second.analyzer.calls[0]["thread"] == [
        "вас беспокоит служба безопасности",
        "назовите код",
    ]


# ------------------------------------------------------------------ limits


def test_rate_limit_refuses_the_extra_check(state_path: Path) -> None:
    bot = make_harness(state_path, daily_check_limit=3)
    consent(bot)
    for index in range(4):
        bot.feed(message_update(f"проверьте это {index}"))

    assert len(bot.analyzer.calls) == 3
    assert "лимит исчерпан" in bot.last


def test_rate_limit_holds_across_a_restart(state_path: Path) -> None:
    """A limiter that forgets on restart is an invitation to restart."""
    clock = Clock(datetime(2026, 9, 8, 10, 0, tzinfo=UTC))
    first = make_harness(state_path, daily_check_limit=3, clock=clock)
    consent(first)
    for index in range(3):
        first.feed(message_update(f"сообщение {index}"))
    assert len(first.analyzer.calls) == 3

    second = make_harness(state_path, daily_check_limit=3, clock=clock)
    second.feed(message_update("ещё одно"))

    assert second.analyzer.calls == []
    assert "лимит исчерпан" in second.last


def test_the_limit_resets_on_the_next_local_day(state_path: Path) -> None:
    bot = make_harness(state_path, daily_check_limit=1)
    consent(bot)
    bot.feed(message_update("первая проверка"))
    bot.feed(message_update("вторая проверка"))
    assert len(bot.analyzer.calls) == 1

    bot.clock.advance(days=1)
    bot.clear()
    bot.feed(message_update("завтрашняя проверка"))
    assert len(bot.analyzer.calls) == 1


def test_the_refusal_still_gives_advice(state_path: Path) -> None:
    """Someone out of checks may still be mid-scam. Do not just say no."""
    bot = make_harness(state_path, daily_check_limit=1)
    consent(bot)
    bot.feed(message_update("первая"))
    bot.feed(message_update("вторая"))
    assert "102" in bot.last


def test_oversized_text_is_refused_before_analysis(state_path: Path) -> None:
    bot = make_harness(state_path, max_text_chars=50)
    consent(bot)
    bot.feed(message_update("а" * 80))

    assert bot.analyzer.calls == []
    assert "слишком длинное" in bot.last


def test_a_refused_message_does_not_spend_a_check(state_path: Path) -> None:
    """Rejecting an oversized message is free, so it must not cost the user."""
    bot = make_harness(state_path, max_text_chars=50, daily_check_limit=1)
    consent(bot)
    bot.feed(message_update("а" * 80))
    bot.feed(message_update("короткое сообщение"))

    assert len(bot.analyzer.calls) == 1


def test_oversized_image_is_refused_without_downloading_it(state_path: Path) -> None:
    bot = make_harness(state_path, max_image_bytes=1024)
    consent(bot)
    bot.feed(message_update(photo=photo(size_bytes=5 * 1024 * 1024)))

    assert "слишком большая" in bot.last
    # No file was requested, so `stream_content` never had the chance to fire.
    assert [type(call).__name__ for call in bot.session.calls] == ["SendMessage"]
    assert bot.analyzer.calls == []


def test_an_image_within_the_cap_is_accepted_for_now(state_path: Path) -> None:
    bot = make_harness(state_path, max_image_bytes=5 * 1024 * 1024)
    consent(bot)
    bot.feed(message_update(photo=photo(size_bytes=200 * 1024)))

    assert "слишком большая" not in bot.last
    assert [type(call).__name__ for call in bot.session.calls] == ["SendMessage"]


def test_unsupported_content_gets_an_explanation(bot: Harness) -> None:
    consent(bot)
    bot.feed(message_update(voice=Voice(file_id="v", file_unique_id="vu", duration=8)))
    assert "Голосовые" in bot.last
    assert bot.analyzer.calls == []


# ----------------------------------------------------------------- privacy


def _log_text(records: list[logging.LogRecord]) -> str:
    return "\n".join(f"{record.name} {record.getMessage()}" for record in records)


def test_no_raw_telegram_id_is_ever_logged(
    state_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The identifier that names a real person never reaches a log record."""
    bot = make_harness(state_path, daily_check_limit=1)
    with caplog.at_level(logging.DEBUG):
        bot.feed(message_update("/start"))
        bot.feed(callback_update("lang:ru"))
        bot.feed(message_update("Назовите код из СМС"))
        bot.feed(message_update("вторая проверка, за лимитом"))
        bot.feed(message_update(photo=photo(size_bytes=50 * 1024 * 1024)))
        bot.feed(message_update("/privacy"))

    logged = _log_text(caplog.records)
    assert logged, "expected the handlers to log something at all"
    assert str(USER_ID) not in logged
    assert str(CHAT_ID) not in logged
    # And the actor is still traceable through the hash, or the logs are useless.
    assert short_ref(actor_hash(SECRET, USER_ID)) in logged


def test_no_raw_telegram_id_is_ever_written_to_disk(state_path: Path) -> None:
    bot = make_harness(state_path)
    bot.feed(message_update("/start"))
    bot.feed(callback_update("lang:ru"))
    bot.feed(message_update("Назовите код из СМС"))

    saved = state_path.read_text(encoding="utf-8")
    assert str(USER_ID) not in saved
    assert actor_hash(SECRET, USER_ID) in saved
    assert chat_key(SECRET, CHAT_ID) in saved


def test_actor_and_chat_hashes_are_different_for_the_same_id() -> None:
    """Private chats share the integer; the two tables must not be joinable."""
    assert actor_hash(SECRET, USER_ID) != chat_key(SECRET, USER_ID)


def test_hashing_depends_on_the_secret() -> None:
    assert actor_hash("one", USER_ID) != actor_hash("two", USER_ID)


def test_config_refuses_to_start_without_a_hash_secret() -> None:
    with pytest.raises(RuntimeError, match="ACTOR_HASH_SECRET"):
        BotConfig.from_env({"TELEGRAM_BOT_TOKEN": TOKEN})


def test_config_reads_the_documented_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    config = BotConfig.from_env(
        {
            "ACTOR_HASH_SECRET": SECRET,
            "DAILY_CHECK_LIMIT": "7",
            "MAX_TEXT_CHARS": "1234",
            "MAX_IMAGE_BYTES": "4096",
            "TEXT_RETENTION_DAYS": "14",
        }
    )
    assert (config.daily_check_limit, config.max_text_chars) == (7, 1234)
    assert (config.max_image_bytes, config.text_retention_days) == (4096, 14)


# -------------------------------------------------------------------- seam


def test_build_deps_falls_back_to_stubs_when_a_lane_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bot has to start before the pipeline and the renderer exist.

    `sys.modules[name] = None` is the documented way to make an import of that
    name raise, which is what the absent lane looks like from in here.
    """
    monkeypatch.setitem(sys.modules, "saqbol.pipeline", None)
    monkeypatch.setitem(sys.modules, "saqbol.core.render", None)

    config = BotConfig(actor_hash_secret=SECRET, state_path=tmp_path / "bot.json")
    deps = build_deps(config)

    assert deps.analyze_is_stub is True
    assert deps.renderer_is_stub is True


def test_build_deps_wires_the_real_lanes_once_they_land(tmp_path: Path) -> None:
    pytest.importorskip("saqbol.pipeline")
    pytest.importorskip("saqbol.core.render")

    config = BotConfig(actor_hash_secret=SECRET, state_path=tmp_path / "bot.json")
    deps = build_deps(config)

    assert deps.analyze_is_stub is False
    assert deps.renderer_is_stub is False


def test_the_real_card_satisfies_the_card_protocol() -> None:
    """The seam holds: whatever the renderer lane shipped, `cards.py` can lay out."""
    render = pytest.importorskip("saqbol.core.render")
    verdict = asyncio.run(stub_analyze("назовите код из СМС", locale=Lang.RU, surface="telegram"))
    card = render.render_card(verdict, Lang.RU)

    assert isinstance(card, Card)
    laid_out = format_card(card, Lang.RU)
    assert laid_out.strip()
    assert len(laid_out) <= 4096


def test_the_stub_card_satisfies_the_card_protocol() -> None:
    verdict = asyncio.run(stub_analyze("код из СМС", locale=Lang.RU, surface="telegram"))
    card = stub_render_card(verdict, Lang.RU)
    assert isinstance(card, Card)


def test_the_stub_verdict_keeps_the_evidence_span_invariant() -> None:
    """D4: `normalized[span.start:span.end] == span.text`, stubs included."""
    text = "Здравствуйте, назовите код из СМС для отмены операции"
    verdict = asyncio.run(stub_analyze(text, locale=Lang.RU, surface="telegram"))
    assert verdict.evidence
    assert all(span.matches(text) for span in verdict.evidence)


def test_adapt_analyze_drops_arguments_the_pipeline_does_not_take() -> None:
    """The pinned `analyze` has no `thread` or `metadata`. It must still work."""
    seen: dict[str, Any] = {}

    async def pinned(text: str, *, locale: Lang, surface: str) -> Verdict:
        seen.update(text=text, locale=locale, surface=surface)
        return await stub_analyze(text, locale=locale, surface=surface)

    adapted = adapt_analyze(pinned)
    asyncio.run(
        adapted(
            "код",
            locale=Lang.RU,
            surface="telegram",
            thread=["код"],
            metadata={"is_forward": True},
        )
    )
    assert seen == {"text": "код", "locale": Lang.RU, "surface": "telegram"}


def test_adapt_analyze_passes_through_what_the_pipeline_does_take() -> None:
    seen: dict[str, Any] = {}

    async def extended(
        text: str,
        *,
        locale: Lang,
        surface: str,
        thread: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Verdict:
        seen.update(thread=thread, metadata=metadata)
        return await stub_analyze(text, locale=locale, surface=surface)

    adapted = adapt_analyze(extended)
    asyncio.run(
        adapted(
            "код",
            locale=Lang.RU,
            surface="telegram",
            thread=["код"],
            metadata={"is_forward": True},
        )
    )
    assert seen == {"thread": ["код"], "metadata": {"is_forward": True}}


def test_a_broken_pipeline_does_not_break_the_chat(state_path: Path) -> None:
    async def exploding(text: str, **kwargs: Any) -> Verdict:
        msg = "provider is down"
        raise RuntimeError(msg)

    bot = make_harness(state_path)
    bot.deps.__dict__["analyze"] = exploding  # frozen dataclass, test-only swap
    consent(bot)
    bot.feed(message_update("проверьте это сообщение"))

    assert "Попробуйте ещё раз" in bot.last
    # A failed check still has to leave the reader with something to do.
    assert "перезвоните в банк" in bot.last


# ------------------------------------------------------------------- store


def test_a_corrupt_state_file_does_not_stop_the_bot(state_path: Path) -> None:
    state_path.write_text("{ this is not json", encoding="utf-8")
    bot = make_harness(state_path)
    bot.feed(message_update("/start"))
    assert "Скриншоты не сохраняются" in bot.transcript


def test_storage_writes_are_atomic(state_path: Path) -> None:
    """A flush leaves the state file valid and no temporary files behind."""
    bot = make_harness(state_path)
    bot.feed(message_update("/start"))
    leftovers = list(state_path.parent.glob(".bot-state-*"))
    assert leftovers == []
    assert state_path.read_text(encoding="utf-8").strip().startswith("{")
