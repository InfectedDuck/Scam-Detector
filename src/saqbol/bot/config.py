"""Bot configuration, read from the environment exactly once at startup.

Every knob here has a matching line in `.env.example`. Nothing in this module
reads the network or touches Telegram, so it is importable from tests.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

from saqbol.core.types import Lang

log = logging.getLogger(__name__)

#: Kazakhstan has run on a single UTC+5 offset with no daylight saving since
#: March 2024. A fixed offset is used rather than a zoneinfo key because the tz
#: database is not installed with Python on Windows, and this is the one place a
#: missing timezone would silently move the daily reset. The reset therefore
#: lands at local midnight instead of at 05:00, which is what a UTC day boundary
#: would have given a user in Almaty.
KZ_TZ = timezone(timedelta(hours=5), "UTC+5")

#: The value shipped in `.env.example`. Running with it is not fatal, because it
#: would block a first local run, but it makes actor hashes guessable and so it
#: is called out loudly.
PLACEHOLDER_SECRET = "change_me_to_32_random_bytes"


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("%s is not an integer (%r); falling back to %d", key, raw, default)
        return default


@dataclass(frozen=True)
class BotConfig:
    """Runtime limits and secrets.

    `token` is optional so that the whole bot can be constructed in a test with
    no credentials. `main.run` is the only caller that insists on one.
    """

    actor_hash_secret: str
    token: str | None = None
    daily_check_limit: int = 10
    max_text_chars: int = 8000
    max_image_bytes: int = 5 * 1024 * 1024
    text_retention_days: int = 30
    state_path: Path = Path(".state/bot.json")
    #: Messages arriving within this many seconds of the previous one are
    #: treated as one conversation, which is what stage detection reads.
    thread_window_seconds: int = 900
    thread_max_messages: int = 8
    default_locale: Lang = Lang.RU

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BotConfig:
        env = os.environ if env is None else env
        secret = (env.get("ACTOR_HASH_SECRET") or "").strip()
        if not secret:
            msg = (
                "ACTOR_HASH_SECRET is empty. Actor hashing is the only thing "
                "keeping raw Telegram ids out of storage; refusing to start."
            )
            raise RuntimeError(msg)
        if secret == PLACEHOLDER_SECRET:
            log.warning(
                "ACTOR_HASH_SECRET is still the .env.example placeholder. "
                "Actor hashes are guessable until it is replaced."
            )
        return cls(
            actor_hash_secret=secret,
            token=(env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None,
            daily_check_limit=_int_env(env, "DAILY_CHECK_LIMIT", 10),
            max_text_chars=_int_env(env, "MAX_TEXT_CHARS", 8000),
            max_image_bytes=_int_env(env, "MAX_IMAGE_BYTES", 5 * 1024 * 1024),
            text_retention_days=_int_env(env, "TEXT_RETENTION_DAYS", 30),
            state_path=Path((env.get("BOT_STATE_PATH") or ".state/bot.json").strip()),
            thread_window_seconds=_int_env(env, "THREAD_WINDOW_SECONDS", 900),
            thread_max_messages=_int_env(env, "THREAD_MAX_MESSAGES", 8),
        )
