"""Command, message and button handlers.

One router, registered in order. Handlers reach the outside world only through
`Deps`, so this module imports nothing outside the bot package and the whole set
runs against a fake transport with no token, no network and no database server.

**Logging rule for this file, and it is not negotiable:** a raw Telegram user id
or chat id never reaches a log record, a state file, a database row, or the
pipeline. Ids are turned into an HMAC in `_identity` on the first line that
sees them, and every subsequent line uses `short_ref` of that hash. The id stays
in the aiogram `Message` object, which is where it has to be in order to reply,
and goes no further.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from saqbol.bot.actors import actor_hash, chat_key, short_ref
from saqbol.bot.cards import format_card, share_text
from saqbol.bot.deps import Deps, RenderCard
from saqbol.bot.forwards import SURFACE, forward_metadata
from saqbol.bot.guards import RateLimiter, check_image_size, check_text_size
from saqbol.bot.keyboards import (
    LANGUAGE_CALLBACK_PREFIX,
    VERDICT_CALLBACK_PREFIX,
    VerdictAction,
    VerdictPress,
    compact_check_id,
    dataset_confirm_keyboard,
    language_keyboard,
    parse_language_callback,
    parse_verdict_callback,
    verdict_keyboard,
)
from saqbol.bot.storage import ChatProfile
from saqbol.bot.strings import consent_block, resolve_locale, t
from saqbol.bot.threads import assemble
from saqbol.core.types import Lang, Verdict
from saqbol.db.hashing import hash_actor
from saqbol.db.repo import Store, UnknownCheck

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
    #: The digest a `checks` row carries for this person, made by
    #: `saqbol.db.hashing.hash_actor`. `None` while nothing is being recorded.
    db_actor: str | None = None

    @property
    def has_consented(self) -> bool:
        return self.profile is not None and bool(self.profile.consent_at)


def _identity(deps: Deps, user_id: int, chat_id: int) -> tuple[str, str, str | None]:
    """The only place a raw Telegram id is read. It leaves as HMACs.

    Two are the bot's own, keyed and domain-separated in `actors.py`, for the
    state file and the logs. The third is what the `checks` table validates:
    `saqbol.db.hashing.hash_actor`, which reads its own secret. It is computed
    only when there is a database to write to, and a secret it refuses disables
    recording, not the bot.
    """
    secret = deps.config.actor_hash_secret
    db_actor: str | None = None
    if deps.db is not None:
        try:
            db_actor = hash_actor(user_id)
        except RuntimeError as exc:
            log.warning("checks are not being recorded: %s", exc)
    return actor_hash(secret, user_id), chat_key(secret, chat_id), db_actor


def _session(deps: Deps, user_id: int, chat_id: int) -> Session:
    actor, chat, db_actor = _identity(deps, user_id, chat_id)
    profile = deps.store.get_profile(chat)
    locale = resolve_locale(profile.locale if profile else None)
    return Session(actor=actor, chat=chat, profile=profile, locale=locale, db_actor=db_actor)


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

    is_forward = bool(metadata.get("is_forward", False))
    recorded = await _record_check(
        deps, session, verdict, text, input_type="forward" if is_forward else "text"
    )

    log.info(
        "check done: actor=%s band=%s thread=%d forward=%s recorded=%s remaining=%d",
        short_ref(session.actor),
        verdict.band.value,
        len(thread.texts),
        is_forward,
        recorded,
        decision.remaining,
    )

    check_id = compact_check_id(verdict.check_id)
    if check_id is None:
        log.warning(
            "check id %r is not a UUID; the card goes out without buttons", verdict.check_id
        )
    keyboard = verdict_keyboard(check_id, locale) if check_id else None
    await message.answer(
        format_card(card, locale, notice=_stub_notice(deps, locale)), reply_markup=keyboard
    )


async def _record_check(
    deps: Deps, session: Session, verdict: Verdict, text: str, *, input_type: str
) -> bool:
    """Persist one analysis, off the event loop. True when a row was written.

    A failure here is logged and costs the reader nothing: the card still goes
    out with its buttons, and a press on a check that was never recorded gets
    the "I no longer have that check" reply rather than an error.
    """
    if deps.db is None or session.db_actor is None:
        return False
    try:
        await asyncio.to_thread(
            deps.db.record_check,
            verdict,
            actor_hash=session.db_actor,
            text=text,
            surface=SURFACE,
            input_type=input_type,
        )
    except Exception:
        log.exception("check not recorded: actor=%s", short_ref(session.actor))
        return False
    return True


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


# ------------------------------------------------------------------- buttons


class _Reply(Exception):
    """Stop handling a press and answer with the string named by `key`."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


async def _in_db(session: Session, what: str, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """One `Store` call, off the event loop, with its failures turned into replies.

    `UnknownCheck` is the ordinary case of a button outliving its row — an
    in-memory store that restarted, a check purged by retention — and gets an
    explanation. Anything else is a database problem: logged with its
    traceback, answered with "not right now".
    """
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except UnknownCheck as exc:
        log.info("%s on an unknown check: actor=%s", what, short_ref(session.actor))
        raise _Reply("check_unknown") from exc
    except Exception as exc:
        log.exception("%s failed: actor=%s", what, short_ref(session.actor))
        raise _Reply("feedback_unavailable") from exc


async def _edit_keyboard(message: Message, keyboard: InlineKeyboardMarkup | None) -> None:
    """Best effort. The vote is already in, and a card Telegram will no longer
    let the bot edit must not turn a recorded vote into an error."""
    try:
        await message.edit_reply_markup(reply_markup=keyboard)
    except TelegramAPIError:
        log.info("could not update the buttons under a card")


async def _replace_prompt(message: Message, text: str) -> None:
    """Rewrite the confirmation prompt in place, which also takes its buttons away."""
    try:
        await message.edit_text(text)
    except TelegramAPIError:
        await message.answer(text)


async def _vote(
    callback: CallbackQuery, message: Message, db: Store, session: Session, press: VerdictPress
) -> None:
    correct = press.action is VerdictAction.VOTE_YES
    await _in_db(session, "vote", db.record_feedback, press.check_id, was_correct=correct)
    log.info("vote recorded: actor=%s correct=%s", short_ref(session.actor), correct)
    # The yes/no pair becomes a thanks, so the same card cannot be voted on
    # twice; the share and dataset rows stay where they were.
    await _edit_keyboard(message, verdict_keyboard(press.check_id, session.locale, voted=True))
    await callback.answer(t(session.locale, "vote_thanks"))


async def _share(
    callback: CallbackQuery,
    message: Message,
    db: Store,
    render_card: RenderCard,
    session: Session,
    press: VerdictPress,
) -> None:
    """Re-render the stored verdict as the text a reader forwards on."""
    row = await _in_db(session, "share", db.get_check, press.check_id)
    if row is None:
        raise _Reply("check_unknown")
    verdict = Verdict.model_validate(row.verdict)
    await message.answer(share_text(verdict, session.locale, render_card))
    await callback.answer(t(session.locale, "share_hint"))


async def _dataset_ask(
    callback: CallbackQuery, message: Message, db: Store, session: Session, press: VerdictPress
) -> None:
    """The first press only asks. Nothing is written until the confirmation."""
    row = await _in_db(session, "dataset", db.get_check, press.check_id)
    if row is None:
        raise _Reply("check_unknown")
    if row.consent_dataset:
        raise _Reply("dataset_already")
    await message.answer(
        t(session.locale, "dataset_confirm"),
        reply_markup=dataset_confirm_keyboard(press.check_id, session.locale),
    )
    await callback.answer()


async def _dataset_confirm(
    callback: CallbackQuery, message: Message, db: Store, session: Session, press: VerdictPress
) -> None:
    """Queue the check's scrubbed text for a human reviewer. Never approves anything."""
    row = await _in_db(session, "dataset", db.get_check, press.check_id)
    if row is None:
        raise _Reply("check_unknown")
    if row.consent_dataset:
        raise _Reply("dataset_already")
    await _in_db(session, "dataset", db.submit_candidate, press.check_id)
    log.info("dataset candidate queued: actor=%s", short_ref(session.actor))
    await _replace_prompt(message, t(session.locale, "dataset_added"))
    await callback.answer()


async def on_verdict_button(callback: CallbackQuery, deps: Deps) -> None:
    """The three buttons under a card, and the confirm/cancel pair behind "add".

    Presses are not gated on consent or on the daily limit: a card only exists
    because a consented check was run, and none of this calls the pipeline.
    """
    press = parse_verdict_callback(callback.data)
    message = callback.message
    if press is None or not isinstance(message, Message) or callback.from_user is None:
        await callback.answer()
        return

    session = _session(deps, callback.from_user.id, message.chat.id)
    locale = session.locale

    # The two presses that write nothing and need no database.
    if press.action is VerdictAction.VOTED:
        await callback.answer(t(locale, "vote_already"))
        return
    if press.action is VerdictAction.DATASET_CANCEL:
        await _replace_prompt(message, t(locale, "dataset_cancelled"))
        await callback.answer()
        return

    try:
        if deps.db is None:
            raise _Reply("feedback_unavailable")
        if press.action in (VerdictAction.VOTE_YES, VerdictAction.VOTE_NO):
            await _vote(callback, message, deps.db, session, press)
        elif press.action is VerdictAction.SHARE:
            await _share(callback, message, deps.db, deps.render_card, session, press)
        elif press.action is VerdictAction.DATASET_ASK:
            await _dataset_ask(callback, message, deps.db, session, press)
        elif press.action is VerdictAction.DATASET_CONFIRM:
            await _dataset_confirm(callback, message, deps.db, session, press)
    except _Reply as reply:
        text = t(locale, reply.key)
        if press.action is VerdictAction.DATASET_CONFIRM:
            # The prompt is the bot's own message; the answer replaces it and
            # its buttons, so a dead confirmation cannot be pressed again.
            await _replace_prompt(message, text)
        else:
            await message.answer(text)
        await callback.answer()
    except Exception:
        log.exception("%s failed: actor=%s", press.action.value, short_ref(session.actor))
        await message.answer(t(locale, "feedback_unavailable"))
        await callback.answer()


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
    router.callback_query.register(on_verdict_button, F.data.startswith(VERDICT_CALLBACK_PREFIX))

    router.message.register(on_photo, F.photo)
    router.message.register(on_forward, F.forward_origin, F.text | F.caption)
    router.message.register(on_text, F.text, ~F.text.startswith("/"))
    router.message.register(on_unsupported)

    return router
