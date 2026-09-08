"""SQLAlchemy models for docs/02_DATA_CONTRACTS.md section 4.

These six tables are the whole schema. If you add a column here, add it to the
contract in the same commit.

Three of the invariants in that document are enforced rather than described,
because each of them fails silently and expensively:

* `actor_hash` accepts only an HMAC digest (`hashing.hash_actor`), guarded by a
  validator on the way in and a length constraint in the database, so a raw
  Telegram id cannot be written even by hand-rolled SQL.
* `checks.text_scrubbed` is the only free-text column with a lifetime, and
  `retention.purge_expired_text` is what ends it.
* A `dataset_candidates` row is born `pending`. Approval is a transition made
  by a named reviewer, never an insert.

No table has a bytes column. Images are analysed in memory and the pixels are
discarded; what survives is the verdict and the hash of the extracted text.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Uuid,
    event,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import REAL

from saqbol.db.base import Base, BigIntPK, EmbeddingColumn, JSONColumn
from saqbol.db.hashing import DIGEST_LENGTH, is_actor_hash

STATUS_PENDING: Final = "pending"
STATUS_APPROVED: Final = "approved"
STATUS_REJECTED: Final = "rejected"
CANDIDATE_STATUSES: Final = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)

SOURCE_PRESS: Final = "press"
CANDIDATE_SOURCES: Final = (SOURCE_PRESS, "donated", "synthetic")

_STATUS_LIST = ", ".join(f"'{s}'" for s in CANDIDATE_STATUSES)


def _reject_raw_identifier(field: str, value: object) -> str:
    if not is_actor_hash(value):
        shape = len(value) if isinstance(value, str) else type(value).__name__
        raise ValueError(
            f"{field} must be an HMAC-SHA256 digest from saqbol.db.hashing.hash_actor(); "
            f"got {shape}. Raw identifiers are never stored."
        )
    return str(value)


class Check(Base):
    """One analysis. The text expires; the verdict and its hash do not."""

    __tablename__ = "checks"
    __table_args__ = (
        CheckConstraint(f"length(actor_hash) = {DIGEST_LENGTH}", name="actor_hash_is_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    input_type: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    #: NULL once the retention job has run. Never the original text: whatever
    #: is stored here has already been through core.privacy.scrub.
    text_scrubbed: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    playbook_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    band: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[float] = mapped_column(REAL(), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    consent_dataset: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    #: HMAC of a Telegram user id or a client IP. See saqbol.db.hashing.
    actor_hash: Mapped[str] = mapped_column(Text, nullable=False)

    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="check", cascade="all, delete-orphan", passive_deletes=True
    )

    @validates("actor_hash")
    def _validate_actor_hash(self, key: str, value: object) -> str:
        return _reject_raw_identifier(key, value)


class Feedback(Base):
    """A "was this right?" vote. Feeds the review queue, never the dataset."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    check_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("checks.id", ondelete="CASCADE"), nullable=True
    )
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    check: Mapped[Check | None] = relationship(back_populates="feedback")


class DatasetCandidate(Base):
    """A row waiting for a human on its way into KazScam.

    Nothing arrives approved. `status` is fixed at `pending` on insert and only
    `approve`/`reject` move it, both of which demand a named reviewer. The
    `decided_rows_are_reviewed` constraint holds the same line against SQL that
    never goes through the ORM.
    """

    __tablename__ = "dataset_candidates"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="status_known"),
        CheckConstraint(
            f"source <> '{SOURCE_PRESS}' OR source_url IS NOT NULL",
            name="press_needs_source_url",
        ),
        CheckConstraint(
            f"status = '{STATUS_PENDING}' OR (reviewer IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="decided_rows_are_reviewed",
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    check_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("checks.id"), nullable=True
    )
    #: Already scrubbed, and kept: this one is the corpus.
    text_scrubbed: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=STATUS_PENDING, server_default=STATUS_PENDING
    )
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def approve(self, reviewer: str, *, when: datetime | None = None) -> None:
        self._decide(STATUS_APPROVED, reviewer, when)

    def reject(self, reviewer: str, reason: str, *, when: datetime | None = None) -> None:
        if not reason.strip():
            raise ValueError("A rejection needs a reason; the queue is reviewed by people.")
        self.reject_reason = reason
        self._decide(STATUS_REJECTED, reviewer, when)

    def _decide(self, status: str, reviewer: str, when: datetime | None) -> None:
        if not reviewer.strip():
            raise ValueError("A dataset decision must name its reviewer.")
        if self.status != STATUS_PENDING:
            raise ValueError(f"Candidate is already {self.status}; decisions are made once.")
        self.status = status
        self.reviewer = reviewer
        self.reviewed_at = when or datetime.now(UTC)


@event.listens_for(DatasetCandidate, "init")
def _new_candidates_start_pending(target: DatasetCandidate, args: tuple, kwargs: dict) -> None:
    """Give a brand new object the status the column would give it at insert.

    Without this the attribute reads None until the first flush, so review code
    holding an uncommitted candidate cannot tell pending from decided.
    """
    kwargs.setdefault("status", STATUS_PENDING)


@event.listens_for(DatasetCandidate, "before_insert")
def _candidates_are_born_pending(mapper: object, connection: object, target: DatasetCandidate):
    """Refuse an insert that skips review.

    The column default already produces `pending`; this catches the caller who
    sets the field explicitly, which is the only way that default is ever lost.
    """
    if target.status is None:
        target.status = STATUS_PENDING
    elif target.status != STATUS_PENDING:
        raise ValueError(
            f"dataset_candidates rows are inserted as '{STATUS_PENDING}', not "
            f"'{target.status}'. Insert, then call approve() or reject() as a reviewer."
        )


class Playbook(Base):
    """The retrieval corpus: one row per scam script, with its embedding."""

    __tablename__ = "playbooks"
    __table_args__ = (
        Index(
            "ix_playbooks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONColumn, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingColumn, nullable=False)


class RateLimit(Base):
    """Per-actor daily counter, keyed by digest like everything else."""

    __tablename__ = "rate_limits"
    __table_args__ = (
        CheckConstraint(f"length(actor_hash) = {DIGEST_LENGTH}", name="actor_hash_is_digest"),
    )

    actor_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    @validates("actor_hash")
    def _validate_actor_hash(self, key: str, value: object) -> str:
        return _reject_raw_identifier(key, value)


class StatsDaily(Base):
    """Materialised nightly for the public stats page. Counts only, no text."""

    __tablename__ = "stats_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    checks: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_actors: Mapped[int] = mapped_column(Integer, nullable=False)
    scam_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unsure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    top_playbook: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "CANDIDATE_SOURCES",
    "CANDIDATE_STATUSES",
    "STATUS_APPROVED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "Check",
    "DatasetCandidate",
    "Feedback",
    "Playbook",
    "RateLimit",
    "StatsDaily",
]
