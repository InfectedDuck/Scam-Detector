"""Persistence layer: the tables in docs/02_DATA_CONTRACTS.md section 4.

Requires the `api` extra (`pip install -e ".[api]"`).

`retention` is deliberately not imported here. It is run as
`python -m saqbol.db.retention`, and a package that imports its own
__main__ module makes the interpreter warn about the double import.
"""

from __future__ import annotations

from saqbol.db.base import EMBEDDING_DIM, Base
from saqbol.db.hashing import actor_secret, hash_actor, is_actor_hash
from saqbol.db.models import (
    CANDIDATE_SOURCES,
    CANDIDATE_STATUSES,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    Check,
    DatasetCandidate,
    Feedback,
    Playbook,
    RateLimit,
    StatsDaily,
)
from saqbol.db.session import build_engine, build_sessionmaker, database_url, session_scope

__all__ = [
    "CANDIDATE_SOURCES",
    "CANDIDATE_STATUSES",
    "EMBEDDING_DIM",
    "STATUS_APPROVED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "Base",
    "Check",
    "DatasetCandidate",
    "Feedback",
    "Playbook",
    "RateLimit",
    "StatsDaily",
    "actor_secret",
    "build_engine",
    "build_sessionmaker",
    "database_url",
    "hash_actor",
    "is_actor_hash",
    "session_scope",
]
