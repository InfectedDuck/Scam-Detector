"""Multi-message thread assembly.

A scam is a script that runs over several messages, and the stage a victim has
reached — contact, hook, trust, pressure, extraction, cashout — is only visible
across them. A single message read alone is often unremarkable: "yes, that's
me" is the extraction step of a hijacked-account script and nothing at all on
its own.

So consecutive messages from one chat, arriving inside a window, are carried
forward and passed to the pipeline as `thread`. The heuristic is deliberately
crude — time proximity, nothing else. A bot cannot see whether two pasted
messages came from the same conversation, and inventing a similarity threshold
here would be a hidden classifier nobody evaluates.

The window is short by design. Someone who comes back in the evening with an
unrelated message must not have it read as a continuation of this morning's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Stored entries are `[text, epoch_seconds]` rather than objects, because the
#: store is JSON and a tuple round-trips as a list anyway.
Entry = list


@dataclass(frozen=True)
class Assembled:
    #: What to write back to the profile.
    entries: list[Entry]
    #: What to hand the pipeline, oldest first, current message last.
    texts: list[str]

    @property
    def is_continuation(self) -> bool:
        return len(self.texts) > 1


def assemble(
    stored: list[Entry],
    text: str,
    *,
    now: datetime,
    window_seconds: int,
    max_messages: int,
) -> Assembled:
    """Fold a new message into the open thread for a chat.

    Entries older than the window are dropped, not archived: the thread is
    context for the next verdict, and this bot has no reason to hold a
    conversation longer than it is being used.
    """
    cutoff = now.timestamp() - window_seconds
    kept: list[Entry] = []
    for entry in stored:
        try:
            entry_text, entry_ts = entry[0], float(entry[1])
        except (IndexError, TypeError, ValueError):
            continue  # a malformed row from an older state file
        if entry_ts >= cutoff and isinstance(entry_text, str):
            kept.append([entry_text, entry_ts])

    kept.append([text, now.timestamp()])
    if max_messages > 0:
        kept = kept[-max_messages:]
    return Assembled(entries=kept, texts=[entry[0] for entry in kept])
