"""Abuse guards: size caps and the per-actor daily limit.

Two separate jobs, deliberately not merged.

The **size caps** exist to stop one message costing an unbounded amount of
work. They are checked before anything else touches the message, and a message
they reject does *not* spend a check from the daily allowance: rejecting it is
free, and charging a confused user for sending too much text would be a poor
trade.

The **daily limit** protects the LLM budget, which is the actual scarce
resource. It is keyed on an HMAC of the Telegram user id and stored on disk, so
it survives a restart. A limiter that resets when the process restarts is not a
limiter; it is an invitation to restart the process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from saqbol.bot.config import KZ_TZ
from saqbol.bot.storage import BotStore, Usage


@dataclass(frozen=True)
class SizeRejection:
    """Why a message was refused before processing."""

    kind: str  # "text" | "image"
    actual: int
    limit: int


def check_text_size(text: str, limit: int) -> SizeRejection | None:
    if len(text) <= limit:
        return None
    return SizeRejection(kind="text", actual=len(text), limit=limit)


def check_image_size(size_bytes: int | None, limit: int) -> SizeRejection | None:
    """Telegram reports `file_size` in the update, before any download.

    So an oversized image is refused without a single byte crossing the wire,
    which is the point: the cap is a download guard, not a decode guard.
    `None` means Telegram did not report a size, in which case there is nothing
    to check yet and the download step in T203 must re-check after streaming.
    """
    if size_bytes is None or size_bytes <= limit:
        return None
    return SizeRejection(kind="image", actual=size_bytes, limit=limit)


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    used: int
    limit: int
    resets_at: datetime

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def local_day(moment: datetime, tz: tzinfo = KZ_TZ) -> str:
    """The calendar day the limit is counted against, as `YYYY-MM-DD`.

    Counted in Kazakhstan local time rather than UTC so that "ten a day" resets
    at the user's midnight. On UTC it would reset at five in the morning, which
    nobody would be able to predict from the message the bot sends them.
    """
    return moment.astimezone(tz).date().isoformat()


def next_reset(moment: datetime, tz: tzinfo = KZ_TZ) -> datetime:
    local = moment.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(days=1)


class RateLimiter:
    """`limit` checks per hashed actor per local day, persisted."""

    def __init__(self, store: BotStore, limit: int, tz: tzinfo = KZ_TZ) -> None:
        self.store = store
        self.limit = limit
        self.tz = tz

    def peek(self, actor_hash: str, now: datetime) -> LimitDecision:
        """Current standing, without spending anything."""
        day = local_day(now, self.tz)
        usage = self.store.get_usage(actor_hash)
        used = usage.count if usage.day == day else 0
        return LimitDecision(
            allowed=used < self.limit,
            used=used,
            limit=self.limit,
            resets_at=next_reset(now, self.tz),
        )

    def consume(self, actor_hash: str, now: datetime) -> LimitDecision:
        """Spend one check if there is one to spend.

        Returns the decision *after* the attempt: on success `used` includes the
        check just taken, and on refusal nothing is written.
        """
        decision = self.peek(actor_hash, now)
        if not decision.allowed:
            return decision
        used = decision.used + 1
        self.store.put_usage(actor_hash, Usage(day=local_day(now, self.tz), count=used))
        return LimitDecision(
            allowed=True,
            used=used,
            limit=self.limit,
            resets_at=decision.resets_at,
        )
