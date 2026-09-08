"""Command and message handlers.

One router, registered in order. Handlers reach the outside world only through
`Deps`, so this module imports nothing that another lane owns and the whole set
runs against a fake transport with no token and no network.

**Logging rule for this file, and it is not negotiable:** a raw Telegram user id
or chat id never reaches a log record, a state file, or the pipeline. Ids are
turned into an HMAC in `_identity` on the first line that sees them, and every
subsequent line uses `short_ref` of that hash. The id stays in the aiogram
`Message` object, which is where it has to be in order to reply, and goes no
further.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from saqbol.bot.actors import actor_hash, chat_key, short_ref
from saqbol.bot.cards import format_card
from saqbol.bot.deps import Deps
from saqbol.bot.forwards import SURFACE, forward_metadata
from saqbol.bot.guards import RateLimiter, check_image_size, check_text_size
from saqbol.bot.keyboards import (
    LANGUAGE_CALLBACK_PREFIX,
    language_keyboard,
    parse_language_callback,
)
from saqbol.bot.storage import ChatProfile
from saqbol.bot.strings import consent_block, resolve_locale, t
from saqbol.bot.threads import assemble
from saqbol.core.types import Lang

log = logging.getLogger(__name__)

#: Languages the consent flow speaks before a choice has been made.
CONSENT_LANGUAGES = (Lang.RU, Lang.KK)

_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class Session:
    """One conversation, already de-identified."""

    actor: str
    chat: str
    profile: ChatProfile | None
    locale: Lang

    @property
    def has_consented(self) -> bool:
        return self.profile is not None and bool(self.profile.consent_at)


def _identity(deps: Deps, user_id: int, chat_id: int) -> tuple[str, str]:
    """The only place a raw Telegram id is read. It leaves as two HMACs."""
    secret = deps.config.actor_hash_secret
    return actor_hash(secret, user_id), chat_key(secret, chat_id)


def _session(deps: Deps, user_id: int, chat_id: int) -> Session:
    actor, chat = _identity(deps, user_id, chat_id)
    profile = deps.store.get_profile(chat)
    locale = resolve_locale(profile.locale if profile else None)
    return Session(actor=actor, chat=chat, profile=profile, locale=locale)


def _bilingual(key: str, separator: str = "\n", **kwargs: object) -> str:
    """A prompt in Russian and Kazakh, for use before a language is chosen."""
    return separator.join(t(lang, key, **kwargs) for lang in CONSENT_LANGUAGES)


def _stub_notice(deps: Deps, locale: Lang) -> str | None:
    if deps.analyze_is_stub or deps.renderer_is_stub:
        return t(locale, "stub_notice")
    return None


async def _send_consent(message: Message, deps: Deps, *, preamble: bool) -> None:
    """The `/start` text: both languages, then the language picker.

    Both languages are always shown. Guessing from the Telegram client language
    would get it wrong often — most phones in Kazakhstan report `ru` whatever
    their owner actually reads — and consent the reader cannot read is not
    consent.
    """
    body = consent_block(deps.config.text_retention_days)
    if preamble:
        body = f"{_bilingual('consent_required')}\n\n{body}"
    await message.answer(body)
    await message.answer(_bilingual("choose_language"), reply_markup=language_keyboard())


# ------------------------------------------------------------------ commands


async def cmd_start(message: Message, deps: Deps) -> None:
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)
    profile = session.profile or ChatProfile()
    profile.consent_at = deps.now().isoformat()
    deps.store.put_profile(session.chat, profile)
    log.info("start: actor=%s", short_ref(session.actor))
    await _send_consent(message, deps, preamble=False)


async def cmd_help(message: Message, deps: Deps) -> None:
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)
    body = t(session.locale, "help", limit=deps.config.daily_check_limit)
    notice = _stub_notice(deps, session.locale)
    await message.answer(f"{notice}\n\n{body}" if notice else body)


async def cmd_privacy(message: Message, deps: Deps) -> None:
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)
    await message.answer(
        t(session.locale, "privacy", retention_days=deps.config.text_retention_days)
    )


async def cmd_forget(message: Message, deps: Deps) -> None:
    """Drop the language, the open thread and the consent record for this chat.

    The daily counter is keyed on the actor rather than the chat and is left
    alone on purpose: it is an abuse guard, and one that a user can clear on
    demand does not guard anything.
    """
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)
    deps.store.forget_chat(session.chat)
    log.info("forget: actor=%s", short_ref(session.actor))
    await message.answer(t(session.locale, "forgotten"))


async def on_language(callback: CallbackQuery, deps: Deps) -> None:
    locale = parse_language_callback(callback.data)
    message = callback.message
    if locale is None or message is None or callback.from_user is None:
        await callback.answer()
        return

    session = _session(deps, callback.from_user.id, message.chat.id)
    profile = session.profile or ChatProfile()
    profile.locale = locale.value
    if not profile.consent_at:
        # Choosing a language is only reachable from the consent message, so it
        # doubles as the acknowledgement when /start was never issued.
        profile.consent_at = deps.now().isoformat()
    deps.store.put_profile(session.chat, profile)
    log.info("language set: actor=%s locale=%s", short_ref(session.actor), locale.value)

    await callback.answer()
    await message.answer(t(locale, "language_set"))


# ------------------------------------------------------------------ messages


async def _run_check(message: Message, deps: Deps) -> None:
    """The shared path for plain text and forwarded text.

    Order is load-bearing. Size caps run before anything else, and before the
    daily limit, so that an oversized message is refused for free. The limit is
    then spent *before* the pipeline is called rather than after: it guards an
    LLM budget, and a counter incremented after the call is a counter that a
    crash or two concurrent messages can walk straight past.
    """
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)

    if not session.has_consented:
        await _send_consent(message, deps, preamble=True)
        return

    profile = session.profile
    assert profile is not None  # implied by has_consented
    locale = session.locale
    text = message.text or message.caption or ""
    if not text.strip():
        await message.answer(t(locale, "send_something"))
        return

    rejected = check_text_size(text, deps.config.max_text_chars)
    if rejected is not None:
        log.info(
            "refused oversized text: actor=%s chars=%d limit=%d",
            short_ref(session.actor),
            rejected.actual,
            rejected.limit,
        )
        await message.answer(
            t(locale, "text_too_long", actual=rejected.actual, limit=rejected.limit)
        )
        return

    limiter = RateLimiter(deps.store, deps.config.daily_check_limit)
    decision = limiter.consume(session.actor, deps.now())
    if not decision.allowed:
        log.info("rate limited: actor=%s used=%d", short_ref(session.actor), decision.used)
        await message.answer(t(locale, "rate_limited", limit=decision.limit))
        return

    now = deps.now()
    thread = assemble(
        profile.thread,
        text,
        now=now,
        window_seconds=deps.config.thread_window_seconds,
        max_messages=deps.config.thread_max_messages,
    )
    profile.thread = thread.entries
    deps.store.put_profile(session.chat, profile)

    metadata = forward_metadata(message, now=now)

    try:
        verdict = await deps.analyze(
            text,
            locale=locale,
            surface=SURFACE,
            thread=thread.texts,
            metadata=metadata,
        )
        card = deps.render_card(verdict, locale)
    except Exception:
        # No id in the record; the traceback is the useful part.
        log.exception("check failed: actor=%s", short_ref(session.actor))
        await message.answer(t(locale, "error"))
        return

    log.info(
        "check done: actor=%s band=%s thread=%d forward=%s remaining=%d",
        short_ref(session.actor),
        verdict.band.value,
        len(thread.texts),
        metadata.get("is_forward", False),
        decision.remaining,
    )
    await message.answer(format_card(card, locale, notice=_stub_notice(deps, locale)))


async def on_photo(message: Message, deps: Deps) -> None:
    """Screenshots. The size cap is enforced here; OCR arrives with T203.

    The cap is checked against the `file_size` Telegram puts in the update, so
    an oversized image is refused without a byte being downloaded.
    """
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)
    if not session.has_consented:
        await _send_consent(message, deps, preamble=True)
        return

    largest = message.photo[-1] if message.photo else None
    rejected = check_image_size(largest.file_size if largest else None, deps.config.max_image_bytes)
    if rejected is not None:
        log.info(
            "refused oversized image: actor=%s bytes=%d limit=%d",
            short_ref(session.actor),
            rejected.actual,
            rejected.limit,
        )
        await message.answer(
            t(
                session.locale,
                "image_too_large",
                actual=f"{rejected.actual / _BYTES_PER_MB:.1f}",
                limit=f"{rejected.limit / _BYTES_PER_MB:.1f}",
            )
        )
        return

    # T203 continues from here: spend a check, download, OCR, discard the bytes.
    # Nothing above this line has touched the image.
    await message.answer(t(session.locale, "photo_not_supported"))


async def on_forward(message: Message, deps: Deps) -> None:
    """A forwarded message, whose provenance feeds indicator family I."""
    await _run_check(message, deps)


async def on_text(message: Message, deps: Deps) -> None:
    await _run_check(message, deps)


async def on_unsupported(message: Message, deps: Deps) -> None:
    """Anything else: voice, video, documents, and unknown commands."""
    if message.from_user is None:
        return
    session = _session(deps, message.from_user.id, message.chat.id)
    if (message.text or "").startswith("/"):
        await message.answer(t(session.locale, "help", limit=deps.config.daily_check_limit))
        return
    await message.answer(t(session.locale, "unsupported"))


def build_router() -> Router:
    """Build a fresh router with the handlers registered in dispatch order.

    Registration is explicit and lives in one block rather than being scattered
    across decorators, because the order is load-bearing and a reviewer has to
    be able to see it: photos are claimed before forwards, and forwards before
    plain text, since a forwarded photo is both and a forwarded message carries
    `text` just like a typed one.

    A factory rather than a module-level singleton, because a `Router` may only
    ever be attached to one `Dispatcher`, and a global one cannot be built twice
    in a process — which every test in this suite needs to do.
    """
    router = Router(name="saqbol")

    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_privacy, Command("privacy"))
    router.message.register(cmd_forget, Command("forget"))
    router.callback_query.register(on_language, F.data.startswith(LANGUAGE_CALLBACK_PREFIX))

    router.message.register(on_photo, F.photo)
    router.message.register(on_forward, F.forward_origin, F.text | F.caption)
    router.message.register(on_text, F.text, ~F.text.startswith("/"))
    router.message.register(on_unsupported)

    return router
