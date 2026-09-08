"""Actor identity hashing.

The database never sees a Telegram user id or a client IP. Every identifier is
reduced to `HMAC-SHA256(ACTOR_HASH_SECRET, value)` at the edge, and the models
refuse any value that is not already a digest, so a caller who forgets to hash
gets an exception rather than a privacy incident.

HMAC rather than a bare hash: SHA-256 over a nine-digit Telegram id is
brute-forced in seconds, and there are only four billion IPv4 addresses. The
secret is what makes the digest one-way in practice. That is also why an unset
or still-default secret is an error here instead of a fallback -- a deployment
that silently hashed with a known key would be indistinguishable from one that
stored the raw ids.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

SECRET_ENV = "ACTOR_HASH_SECRET"

#: HMAC-SHA256, lowercase hex.
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_LENGTH = 64

#: Anything shipped in .env.example. Refusing these is the point.
PLACEHOLDER_PREFIX = "change_me"

#: Short secrets defeat the reason for using HMAC at all.
MIN_SECRET_LENGTH = 16


def actor_secret() -> bytes:
    """The configured HMAC key, or an explanation of why there isn't one."""
    raw = os.environ.get(SECRET_ENV, "").strip()
    if not raw:
        raise RuntimeError(
            f"{SECRET_ENV} is not set. Actor identifiers cannot be stored without it; "
            'generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.'
        )
    if raw.startswith(PLACEHOLDER_PREFIX):
        raise RuntimeError(
            f"{SECRET_ENV} is still the placeholder from .env.example. "
            "A published secret makes the digests reversible by anyone."
        )
    if len(raw) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"{SECRET_ENV} is {len(raw)} characters; at least {MIN_SECRET_LENGTH} are required."
        )
    return raw.encode("utf-8")


def hash_actor(raw: str | int, *, secret: bytes | None = None) -> str:
    """Turn a Telegram user id or an IP address into the value a model accepts.

    This is the only sanctioned way to populate `actor_hash`. The `secret`
    argument exists for tests; production reads the environment.
    """
    value = str(raw).strip()
    if not value:
        raise ValueError("Refusing to hash an empty actor identifier.")
    key = secret if secret is not None else actor_secret()
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def is_actor_hash(value: object) -> bool:
    """True only for something `hash_actor` could have produced."""
    return isinstance(value, str) and DIGEST_RE.match(value) is not None
