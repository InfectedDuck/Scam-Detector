"""Forwarded-message provenance, mapped to indicator family I.

Family I compares what a message *claims* against what the channel *shows*, and
returns nothing when the surface supplied no metadata. Telegram is the only
surface that supplies any, so this module is where family I gets its input.

Two constraints shape what is emitted.

**Only facts Telegram actually reports.** The family I docstring names five
keys, and Telegram gives a bot exactly one of them for a forward:
`has_username`. It reports no sender phone number, no account age, and no
indication of whether the forwarder knows the sender. Those keys are therefore
absent rather than guessed, which is what family I is written to expect —
guessing them would manufacture signal and corrupt the combination bonus that
pairs a claimed institution with a contradicting contact.

Account age deserves a specific note, because it looks derivable: Telegram user
ids increase roughly with registration date, so `account_age_days` could be
estimated from the id. It is not, on both counts that matter here. The estimate
is unreliable enough to fire a MEDIUM indicator on ordinary users, and reading
the id for anything but hashing is exactly what this bot promises not to do.

**No personal data crosses into the pipeline.** A forward carries the sender's
display name and username. Those identify a person, usually a person who has
not used this bot, so they are reduced to a boolean. A public channel is a
different matter: its `@username` is a published identifier and it is what makes
"forwarded from a channel impersonating a bank" checkable, so it is passed
through.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram.types import (
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)

SURFACE = "telegram"


def forward_metadata(message: Message, *, now: datetime | None = None) -> dict[str, Any]:
    """Build the `DetectionContext.metadata` dict for one incoming message.

    Always returns the surface marker, so a detector can tell "channel supplied
    nothing" from "channel was never asked".
    """
    meta: dict[str, Any] = {"surface": SURFACE, "is_forward": False}

    if message.via_bot is not None:
        meta["via_bot"] = True
    if message.is_automatic_forward:
        # A channel post auto-forwarded into its discussion group. Not a
        # person's decision to forward, so it says nothing about a victim.
        meta["is_automatic_forward"] = True

    origin = message.forward_origin
    if origin is None:
        return meta

    meta["is_forward"] = True

    if isinstance(origin, MessageOriginUser):
        meta["forward_origin"] = "user"
        # The one family I key Telegram actually supplies. An account with no
        # public username is cheaper to burn and to replace.
        meta["has_username"] = bool(origin.sender_user.username)
        meta["sender_is_bot"] = bool(origin.sender_user.is_bot)
    elif isinstance(origin, MessageOriginHiddenUser):
        meta["forward_origin"] = "hidden_user"
        # The sender's privacy setting hides the account from forwards. That is
        # weaker provenance, but it is not the same fact as "has no username",
        # so it gets its own key rather than being folded into `has_username`
        # and quietly firing I3.
        meta["forward_hidden_sender"] = True
    elif isinstance(origin, MessageOriginChannel):
        meta["forward_origin"] = "channel"
        meta["forward_channel_username"] = origin.chat.username
        meta["forward_channel_title"] = origin.chat.title
    elif isinstance(origin, MessageOriginChat):
        meta["forward_origin"] = "chat"
        meta["forward_chat_type"] = origin.sender_chat.type
    else:  # pragma: no cover - a new origin type from a future Bot API
        meta["forward_origin"] = getattr(origin, "type", "unknown")

    origin_date = getattr(origin, "date", None)
    if origin_date is not None:
        meta["forward_origin_date"] = origin_date.isoformat()
        reference = now or datetime.now(origin_date.tzinfo)
        age = (reference - origin_date).total_seconds()
        if age >= 0:
            # A forward of something written minutes ago is a live incident; a
            # forward of a year-old post usually is not.
            meta["forward_age_seconds"] = int(age)

    return meta
