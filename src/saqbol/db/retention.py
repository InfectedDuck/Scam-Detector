"""Expire message-bearing data while retaining aggregate check metadata.

Run daily with the same DATABASE_URL and SAQBOL_LLM_CACHE_DIR as the API:

    python -m saqbol.db.retention
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from saqbol.db.models import STATUS_PENDING, STATUS_REJECTED, Check, DatasetCandidate, Feedback
from saqbol.db.session import build_engine, session_scope

RETENTION_ENV = "TEXT_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 30

log = logging.getLogger(__name__)
_CACHE_FILE = re.compile(r"^[0-9a-f]{64}\.json$")
_VERDICT_METADATA = frozenset(
    {
        "check_id",
        "band",
        "risk",
        "playbook_id",
        "playbook_confidence",
        "stage",
        "action_key",
        "hotline",
        "language",
        "components",
        "abstained_because",
        "model",
        "latency_ms",
        "cached",
    }
)


def retention_days() -> int:
    """Days of text kept, from the environment."""
    raw = os.environ.get(RETENTION_ENV, "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{RETENTION_ENV} must be a whole number of days, got {raw!r}") from exc
    if days < 1:
        raise RuntimeError(f"{RETENTION_ENV} must be at least 1, got {days}")
    return days


def cutoff(now: datetime | None = None, days: int | None = None) -> datetime:
    """The timestamp before which text is no longer kept."""
    return (now or datetime.now(UTC)) - timedelta(
        days=days if days is not None else retention_days()
    )


def purge_expired_text(
    session: Session, *, now: datetime | None = None, days: int | None = None
) -> int:
    """NULL the scrubbed text of every check past its retention window.

    Returns the number of rows changed. Idempotent: rows already purged are
    excluded, so a second run in the same night reports zero rather than
    rewriting the whole table.
    """
    before = cutoff(now, days)
    result = session.execute(
        update(Check)
        .where(Check.created_at < before, Check.text_scrubbed.is_not(None))
        .values(text_scrubbed=None)
        .execution_options(synchronize_session=False)
    )
    purged = result.rowcount or 0
    log.info("Purged text from %d checks created before %s", purged, before.isoformat())
    return purged


def purge_expired_verdict_payloads(
    session: Session, *, now: datetime | None = None, days: int | None = None
) -> int:
    """Remove quoted evidence and indicator details from old JSON verdicts.

    The remaining fields are fixed metadata used for statistics and for the
    bot's old share buttons. A whitelist also removes unexpected legacy keys.
    """
    changed = 0
    rows = session.scalars(select(Check).where(Check.created_at < cutoff(now, days)))
    for row in rows:
        retained = {key: value for key, value in row.verdict.items() if key in _VERDICT_METADATA}
        if "indicators" in row.verdict:
            retained["indicators"] = []
        if "evidence" in row.verdict:
            retained["evidence"] = []
        if retained != row.verdict:
            row.verdict = retained
            changed += 1
    log.info("Redacted verdict payloads from %d expired checks", changed)
    return changed


def purge_expired_candidates(
    session: Session, *, now: datetime | None = None, days: int | None = None
) -> int:
    """Discard stale donated submissions never approved for the corpus.

    Pending donations use the linked check's creation date. Rejected rows use
    their review date. Approved rows and non-donated corpus sources remain.
    """
    before = cutoff(now, days)
    stale_checks = select(Check.id).where(Check.created_at < before)
    pending = (
        session.execute(
            delete(DatasetCandidate)
            .where(
                DatasetCandidate.source == "donated",
                DatasetCandidate.status == STATUS_PENDING,
                DatasetCandidate.check_id.in_(stale_checks),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        or 0
    )
    rejected = (
        session.execute(
            delete(DatasetCandidate)
            .where(
                DatasetCandidate.source == "donated",
                DatasetCandidate.status == STATUS_REJECTED,
                DatasetCandidate.reviewed_at < before,
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        or 0
    )
    log.info("Deleted %d pending and %d rejected expired donations", pending, rejected)
    return pending + rejected


def purge_expired_feedback_comments(
    session: Session, *, now: datetime | None = None, days: int | None = None
) -> int:
    """Keep votes for statistics, but stop retaining their free-text comments."""
    changed = (
        session.execute(
            update(Feedback)
            .where(Feedback.created_at < cutoff(now, days), Feedback.comment.is_not(None))
            .values(comment=None)
            .execution_options(synchronize_session=False)
        ).rowcount
        or 0
    )
    log.info("Purged %d expired feedback comments", changed)
    return changed


def purge_expired_cache(root: Path, *, now: datetime | None = None, days: int | None = None) -> int:
    """Remove aged model responses from the production cache volume.

    Only content-addressed cassette files are touched. The modification time
    is when the response was recorded, not when it was last read.
    """
    if not root.exists():
        return 0
    before = cutoff(now, days).timestamp()
    removed = 0
    for shard in root.iterdir():
        if not shard.is_dir() or not re.fullmatch(r"[0-9a-f]{2}", shard.name):
            continue
        for path in shard.iterdir():
            if not path.is_file() or not (
                _CACHE_FILE.fullmatch(path.name) or path.suffix == ".tmp"
            ):
                continue
            try:
                if path.stat().st_mtime < before:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                # A concurrent writer may have renamed its temporary file.
                continue
    log.info("Purged %d expired model cache entries", removed)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days", type=int, default=None, help=f"override {RETENTION_ENV} for this run"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report the cutoff and change nothing"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    days = args.days if args.days is not None else retention_days()
    if days < 1:
        parser.error("--days must be at least 1")
    if args.dry_run:
        log.info("Would expire message-bearing data before %s", cutoff(days=days).isoformat())
        return 0

    engine = build_engine()
    with session_scope(engine) as session:
        candidates = purge_expired_candidates(session, days=days)
        text_rows = purge_expired_text(session, days=days)
        verdicts = purge_expired_verdict_payloads(session, days=days)
        comments = purge_expired_feedback_comments(session, days=days)
    from saqbol.core.llm import DEFAULT_CACHE_DIR, ENV_CACHE_DIR

    cache = purge_expired_cache(Path(os.environ.get(ENV_CACHE_DIR) or DEFAULT_CACHE_DIR), days=days)
    log.info(
        "Retention complete: text=%d verdicts=%d donations=%d comments=%d cache=%d",
        text_rows,
        verdicts,
        candidates,
        comments,
        cache,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
