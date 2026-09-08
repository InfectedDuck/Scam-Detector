"""The one writer for the tables the API and the bot both touch.

Both surfaces record a check, accept a vote on it, and forward a consented
message to the dataset queue. Having two copies of that code would mean two
places where raw text or a raw identifier could slip into a row, so it lives
here once and the surfaces call it.

Three things are enforced on the way in rather than left to the caller:

* text is scrubbed here, so `checks.text_scrubbed` cannot receive the original;
* `actor_hash` must already be a digest from `hashing.hash_actor`, and the
  models refuse anything else;
* a dataset candidate is inserted pending; only a named reviewer moves it.

Everything here is synchronous SQLAlchemy. The bot and the API are async, and
call these from a worker thread (`asyncio.to_thread`) so a slow database
never stalls the event loop for every other user.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from saqbol.core.privacy import scrub
from saqbol.core.types import Band, Verdict
from saqbol.db.base import Base
from saqbol.db.models import Check, DatasetCandidate, Feedback, RateLimit, StatsDaily
from saqbol.db.session import build_engine, session_scope

INPUT_TYPES = ("text", "image", "forward")
SURFACES = ("telegram", "web", "api")


class UnknownCheck(LookupError):
    """A vote or a submission referenced a check that does not exist."""


@dataclass(frozen=True)
class DayStats:
    day: date
    checks: int
    unique_actors: int
    scam_count: int
    unsure_count: int
    top_playbook: str | None


@dataclass(frozen=True)
class StatsSummary:
    """The shape of GET /api/v1/stats (docs/02_DATA_CONTRACTS.md section 5)."""

    total_checks: int
    unique_users: int
    scam_share: float
    days: list[DayStats] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict:
        return {
            "total_checks": self.total_checks,
            "unique_users": self.unique_users,
            "scam_share": self.scam_share,
            "days": [
                {
                    "day": d.day.isoformat(),
                    "checks": d.checks,
                    "unique_actors": d.unique_actors,
                    "scam_count": d.scam_count,
                    "unsure_count": d.unsure_count,
                    "top_playbook": d.top_playbook,
                }
                for d in self.days
            ],
            "updated_at": self.updated_at.isoformat(),
        }


def _as_uuid(check_id: str | uuid.UUID) -> uuid.UUID:
    if isinstance(check_id, uuid.UUID):
        return check_id
    try:
        return uuid.UUID(str(check_id))
    except ValueError as exc:
        raise UnknownCheck(f"{check_id!r} is not a check id") from exc


def text_digest(text: str) -> str:
    """SHA-256 of the scrubbed text. Kept after the text itself is purged."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Store:
    """Thin, explicit persistence for the two surfaces. One engine, short sessions."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @classmethod
    def from_env(cls) -> Store:
        """Production: DATABASE_URL from the environment, schema managed by alembic."""
        return cls(build_engine())

    @classmethod
    def in_memory(cls) -> Store:
        """Tests and local runs without Postgres: SQLite, schema created on the spot."""
        from sqlalchemy.pool import StaticPool

        engine = build_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        return cls(engine)

    # ------------------------------------------------------------ checks

    def record_check(
        self,
        verdict: Verdict,
        *,
        actor_hash: str,
        text: str,
        surface: str,
        input_type: str = "text",
        consent_dataset: bool = False,
        cost_usd: float | None = None,
    ) -> uuid.UUID:
        """Persist one analysis. `text` is the normalized input; it is scrubbed here.

        The row id is the verdict's own check_id, so the id a user sees on a
        card is the id a vote comes back with.
        """
        if surface not in SURFACES:
            raise ValueError(f"surface must be one of {SURFACES}, got {surface!r}")
        if input_type not in INPUT_TYPES:
            raise ValueError(f"input_type must be one of {INPUT_TYPES}, got {input_type!r}")
        scrubbed = scrub(text).text
        row = Check(
            id=_as_uuid(verdict.check_id),
            surface=surface,
            input_type=input_type,
            lang=str(verdict.language),
            text_sha256=text_digest(scrubbed),
            text_scrubbed=scrubbed,
            verdict=verdict.model_dump(mode="json"),
            playbook_id=verdict.playbook_id,
            band=str(verdict.band),
            risk=float(verdict.risk),
            model=verdict.model or "rules_only",
            latency_ms=int(verdict.latency_ms),
            cost_usd=cost_usd,
            consent_dataset=consent_dataset,
            actor_hash=actor_hash,
        )
        with session_scope(self.engine) as session:
            session.add(row)
        return row.id

    def get_check(self, check_id: str | uuid.UUID) -> Check | None:
        with session_scope(self.engine) as session:
            return session.get(Check, _as_uuid(check_id))

    # ---------------------------------------------------------- feedback

    def record_feedback(
        self,
        check_id: str | uuid.UUID,
        *,
        was_correct: bool | None,
        comment: str | None = None,
    ) -> int:
        """A "was this right?" vote. Raises UnknownCheck for an id we never issued."""
        cid = _as_uuid(check_id)
        with session_scope(self.engine) as session:
            if session.get(Check, cid) is None:
                raise UnknownCheck(f"no check {cid}")
            row = Feedback(check_id=cid, was_correct=was_correct, comment=comment or None)
            session.add(row)
            session.flush()
            return row.id

    # ---------------------------------------------- dataset candidates

    def submit_candidate(
        self,
        check_id: str | uuid.UUID,
        *,
        source: str = "donated",
        source_url: str | None = None,
    ) -> int:
        """Queue a check's scrubbed text for human review. Never approves anything.

        The text comes from the check row, not from the caller, so what enters
        the queue is exactly what was scrubbed and stored.
        """
        cid = _as_uuid(check_id)
        with session_scope(self.engine) as session:
            check = session.get(Check, cid)
            if check is None:
                raise UnknownCheck(f"no check {cid}")
            if check.text_scrubbed is None:
                raise UnknownCheck(f"check {cid} has no text left to submit")
            row = DatasetCandidate(
                check_id=cid,
                text_scrubbed=check.text_scrubbed,
                source=source,
                source_url=source_url,
            )
            session.add(row)
            check.consent_dataset = True
            session.flush()
            return row.id

    # ------------------------------------------------------ rate limits

    def count_today(self, actor_hash: str, *, day: date | None = None) -> int:
        d = day or datetime.now(UTC).date()
        with session_scope(self.engine) as session:
            row = session.get(RateLimit, (actor_hash, d))
            return row.count if row is not None else 0

    def spend_check(self, actor_hash: str, *, limit: int, day: date | None = None) -> bool:
        """Consume one check if the actor has any left today. True when allowed.

        The row is locked for the update on databases that support it, so two
        requests racing at the limit cannot both pass.
        """
        d = day or datetime.now(UTC).date()
        with session_scope(self.engine) as session:
            stmt = select(RateLimit).where(RateLimit.actor_hash == actor_hash, RateLimit.day == d)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update()
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                row = RateLimit(actor_hash=actor_hash, day=d, count=0)
                session.add(row)
            if row.count >= limit:
                return False
            row.count += 1
            return True

    # ------------------------------------------------------------ stats

    def materialize_day(self, day: date) -> DayStats:
        """Recompute one day's counts from `checks` into `stats_daily`. Idempotent."""
        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        with session_scope(self.engine) as session:
            window = (Check.created_at >= start, Check.created_at < end)
            checks = session.scalar(select(func.count()).select_from(Check).where(*window)) or 0
            uniques = (
                session.scalar(select(func.count(func.distinct(Check.actor_hash))).where(*window))
                or 0
            )
            scams = (
                session.scalar(
                    select(func.count())
                    .select_from(Check)
                    .where(*window, Check.band == str(Band.SCAM))
                )
                or 0
            )
            unsure = (
                session.scalar(
                    select(func.count())
                    .select_from(Check)
                    .where(*window, Check.band == str(Band.UNSURE))
                )
                or 0
            )
            top = session.execute(
                select(Check.playbook_id, func.count().label("n"))
                .where(*window, Check.playbook_id.is_not(None))
                .group_by(Check.playbook_id)
                .order_by(func.count().desc(), Check.playbook_id)
                .limit(1)
            ).first()
            row = session.get(StatsDaily, day)
            if row is None:
                row = StatsDaily(day=day, checks=0, unique_actors=0, scam_count=0, unsure_count=0)
                session.add(row)
            row.checks = checks
            row.unique_actors = uniques
            row.scam_count = scams
            row.unsure_count = unsure
            row.top_playbook = top[0] if top else None
        return DayStats(day, checks, uniques, scams, unsure, top[0] if top else None)

    def stats_summary(self, *, days: int = 30, now: datetime | None = None) -> StatsSummary:
        """The public numbers, read from `stats_daily` only. No text, no ids.

        `unique_users` is the sum of daily uniques, which over-counts a person
        who returns on another day. The alternative needs actor hashes on the
        public path, and an over-count labelled as such is the safer number.
        """
        current = now or datetime.now(UTC)
        since = current.date() - timedelta(days=days - 1)
        with session_scope(self.engine) as session:
            rows = session.execute(
                select(StatsDaily).where(StatsDaily.day >= since).order_by(StatsDaily.day)
            ).scalars()
            per_day = [
                DayStats(
                    r.day, r.checks, r.unique_actors, r.scam_count, r.unsure_count, r.top_playbook
                )
                for r in rows
            ]
        total = sum(d.checks for d in per_day)
        scams = sum(d.scam_count for d in per_day)
        return StatsSummary(
            total_checks=total,
            unique_users=sum(d.unique_actors for d in per_day),
            scam_share=round(scams / total, 4) if total else 0.0,
            days=per_day,
            updated_at=current,
        )


def session_for(store: Store) -> Session:
    """An open session on the store's engine, for callers that need raw access."""
    return Session(store.engine, expire_on_commit=False)


__all__ = [
    "INPUT_TYPES",
    "SURFACES",
    "DayStats",
    "StatsSummary",
    "Store",
    "UnknownCheck",
    "session_for",
    "text_digest",
]
