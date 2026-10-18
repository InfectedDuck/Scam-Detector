"""Durable bot state: language choice, consent, daily counters, open threads.

A JSON file, flushed on every mutation. That is deliberate and it is not a
placeholder for the database:

* The rate limit has to survive a restart or it is not a rate limit. A process
  redeploy would otherwise hand every actor a fresh allowance.
* None of this is relational, and none of it is the research data. The Postgres
  tables in saqbol.db hold checks, feedback and dataset candidates;
  this file holds only the few facts the bot needs to answer the next message.

Keys are HMACs from `actors.py`. No raw Telegram id is written here, but a
recent thread can still contain sensitive context. Do not copy this file into
bug reports. Thread entries are masked on write and expired by the bot.

The research data — checks, votes, dataset candidates — goes through the shared
`saqbol.db.repo.Store` on `Deps.db` instead, and the two never meet: this file
holds nothing about a check, and the database holds nothing about a chat.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from saqbol.core.privacy import scrub

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class ChatProfile:
    """What the bot remembers about one conversation."""

    #: `None` until the user picks one; handlers fall back to the config default.
    locale: str | None = None
    #: ISO-8601 UTC timestamp of the `/start` that showed the consent text.
    consent_at: str | None = None
    #: `[[text, epoch_seconds], ...]`, oldest first. Trimmed by `threads.py`.
    thread: list[list] = field(default_factory=list)


@dataclass
class Usage:
    """One actor's checks on one local day."""

    day: str = ""
    count: int = 0


class BotStore:
    """Load once, mutate in memory, flush atomically on every write."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict = self._read()

    # ---------------------------------------------------------------- io

    def _read(self) -> dict:
        empty: dict = {"version": SCHEMA_VERSION, "chats": {}, "usage": {}}
        if not self.path.exists():
            return empty
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A truncated state file must not take the bot down. Losing a
            # language choice is recoverable; refusing to start is not.
            log.warning("bot state at %s is unreadable; starting from empty", self.path)
            return empty
        if not isinstance(loaded, dict) or loaded.get("version") != SCHEMA_VERSION:
            log.warning("bot state at %s has an unknown shape; starting from empty", self.path)
            return empty
        loaded.setdefault("chats", {})
        loaded.setdefault("usage", {})
        return loaded

    def flush(self) -> None:
        """Write via a temporary file in the same directory, then rename.

        A half-written state file reads as corrupt on the next start and would
        silently reset every actor's daily counter.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".bot-state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ----------------------------------------------------------- profiles

    def get_profile(self, chat_key: str) -> ChatProfile | None:
        raw = self._data["chats"].get(chat_key)
        if raw is None:
            return None
        return ChatProfile(
            locale=raw.get("locale"),
            consent_at=raw.get("consent_at"),
            thread=list(raw.get("thread") or []),
        )

    def put_profile(self, chat_key: str, profile: ChatProfile) -> None:
        stored = asdict(profile)
        # A thread is useful for the next verdict, but the JSON file must not
        # keep an unmasked copy of a pasted card number or address.
        stored["thread"] = [
            [scrub(entry[0]).text, entry[1]]
            for entry in profile.thread
            if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str)
        ]
        self._data["chats"][chat_key] = stored
        self.flush()

    def purge_expired_threads(self, *, window_seconds: int, now: datetime | None = None) -> int:
        """Drop inactive chat text even when its owner never sends another message."""
        before = (now or datetime.now(UTC)).timestamp() - window_seconds
        changed = 0
        for profile in self._data["chats"].values():
            thread = profile.get("thread") or []
            kept = []
            for entry in thread:
                try:
                    timestamp = float(entry[1])
                except (IndexError, TypeError, ValueError):
                    continue
                if timestamp >= before and isinstance(entry[0], str):
                    kept.append([scrub(entry[0]).text, timestamp])
            if kept != thread:
                profile["thread"] = kept
                changed += 1
        if changed:
            self.flush()
        # A killed process can leave an atomic-write scratch file behind. Old
        # versions may have put raw thread text in it, so clear stale orphans.
        temp_cutoff = (now or datetime.now(UTC)).timestamp() - 3600
        for path in self.path.parent.glob(".bot-state-*.tmp"):
            try:
                if path.stat().st_mtime < temp_cutoff:
                    path.unlink()
            except FileNotFoundError:
                continue
        return changed

    # -------------------------------------------------------------- usage

    def get_usage(self, actor_hash: str) -> Usage:
        raw = self._data["usage"].get(actor_hash)
        if raw is None:
            return Usage()
        return Usage(day=raw.get("day", ""), count=int(raw.get("count", 0)))

    def put_usage(self, actor_hash: str, usage: Usage) -> None:
        self._data["usage"][actor_hash] = asdict(usage)
        self.flush()

    # ------------------------------------------------------------ hygiene

    def forget_chat(self, chat_key: str) -> None:
        """Drop everything held for one conversation.

        Used by `/forget`, and the reason the privacy text can promise that
        stopping the bot actually removes the stored language and thread.
        """
        if self._data["chats"].pop(chat_key, None) is not None:
            self.flush()
