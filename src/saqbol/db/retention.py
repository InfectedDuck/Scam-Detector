"""Text retention.

A check keeps its scrubbed text only long enough to be useful: to show someone
what they asked about, to debug a bad verdict, to promote a donated message
into the corpus. After TEXT_RETENTION_DAYS none of those apply and the text
becomes pure liability, so it is set to NULL.

What survives the purge is deliberate. `text_sha256` stays, so duplicate
submissions still collapse onto one another and the cache keeps working;
`verdict` stays, because the statistics and the eval history are built from it;
`actor_hash` stays, because it was never reversible to begin with.

`dataset_candidates.text_scrubbed` is *not* touched. Those rows were donated
with consent and reviewed by a person -- they are the corpus, not a byproduct
of serving a request.

Run nightly:

    python -m saqbol.db.retention
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from saqbol.db.models import Check
from saqbol.db.session import build_engine, session_scope

RETENTION_ENV = "TEXT_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 30

log = logging.getLogger(__name__)


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
    if args.dry_run:
        log.info("Would purge check text created before %s", cutoff(days=days).isoformat())
        return 0

    engine = build_engine()
    with session_scope(engine) as session:
        purged = purge_expired_text(session, days=days)
    log.info("%d rows purged.", purged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
