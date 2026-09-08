"""Identifier hashing.

A Telegram user id is a stable, cross-service identifier for a real person, and
this bot exists to be trusted by people who are being defrauded. So the raw id
never leaves the handler frame: it is turned into an HMAC immediately and only
the HMAC is stored, counted, or logged.

HMAC rather than a plain SHA-256 because the id space is small and enumerable.
Without a keyed hash, anyone holding the state file could recover every user id
by hashing the integers.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

#: Domain separators, so a chat key and an actor key for the same integer are
#: different values and cannot be correlated across the two tables.
_ACTOR_DOMAIN = b"saqbol/actor/v1:"
_CHAT_DOMAIN = b"saqbol/chat/v1:"


def _digest(secret: str, domain: bytes, value: int | str) -> str:
    mac = hmac.new(secret.encode("utf-8"), domain + str(value).encode("utf-8"), sha256)
    return mac.hexdigest()


def actor_hash(secret: str, user_id: int | str) -> str:
    """Rate-limiting and abuse-guard identity for one person."""
    return _digest(secret, _ACTOR_DOMAIN, user_id)


def chat_key(secret: str, chat_id: int | str) -> str:
    """Storage identity for one conversation.

    In a private chat the Telegram chat id equals the user id, so this is hashed
    for the same reason and with a different domain separator.
    """
    return _digest(secret, _CHAT_DOMAIN, chat_id)


def short_ref(hashed: str) -> str:
    """A 12-character handle for log lines.

    Long enough to follow one actor through a log file while debugging, short
    enough that it is not a durable identifier to leak.
    """
    return hashed[:12]
