"""Database schema, privacy invariants and the retention job.

The schema is docs/02_DATA_CONTRACTS.md section 4, and most of this file is
about the four things that must stay true of it however the code around it
changes:

1. no column anywhere holds a raw identifier, and `actor_hash` accepts nothing
   but an HMAC digest (T205);
2. `checks.text_scrubbed` is nullable and the retention job empties it (T206);
3. no table has an image bytes column (T203);
4. a `dataset_candidates` row is born `pending` and is promoted only by a named
   reviewer (T206).

Each one is asserted twice: against the models, and against the SQL the
migration actually emits, because a model invariant that never reached the
database is decoration.

Everything runs on in-memory SQLite. The tests that need real Postgres --
pgvector, and the migration applied to a live server -- are marked `network`
and skipped in CI.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import os
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="the persistence layer needs the 'api' extra")
pytest.importorskip("pgvector", reason="the persistence layer needs the 'api' extra")

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from saqbol.db import hashing, retention
from saqbol.db.base import EMBEDDING_DIM, Base
from saqbol.db.hashing import hash_actor, is_actor_hash
from saqbol.db.models import (
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
from saqbol.db.retention import purge_expired_text, retention_days

ROOT = Path(__file__).resolve().parents[1]
SECRET = "t" * 48

#: docs/02_DATA_CONTRACTS.md section 4, verbatim and in order.
CONTRACT = {
    "checks": (
        "id",
        "created_at",
        "surface",
        "input_type",
        "lang",
        "text_sha256",
        "text_scrubbed",
        "verdict",
        "playbook_id",
        "band",
        "risk",
        "model",
        "latency_ms",
        "cost_usd",
        "consent_dataset",
        "actor_hash",
    ),
    "feedback": ("id", "check_id", "was_correct", "comment", "created_at"),
    "dataset_candidates": (
        "id",
        "check_id",
        "text_scrubbed",
        "source",
        "source_url",
        "status",
        "reviewer",
        "reviewed_at",
        "reject_reason",
    ),
    "playbooks": ("id", "version", "content", "embedding"),
    "rate_limits": ("actor_hash", "day", "count"),
    "stats_daily": (
        "day",
        "checks",
        "unique_actors",
        "scam_count",
        "unsure_count",
        "top_playbook",
    ),
}

#: Substrings that would betray a raw identifier. A digest column is allowed to
#: mention what it is a digest *of*, which is why the suffix escape exists.
RAW_IDENTIFIER_HINTS = (
    "user_id",
    "userid",
    "telegram",
    "tg_id",
    "chat_id",
    "actor_id",
    "ip_address",
    "client_ip",
    "remote_addr",
    "username",
    "handle",
    "phone",
    "msisdn",
    "email",
    "iin",
    "card_number",
    "device_id",
)
DIGEST_SUFFIXES = ("_hash", "_sha256")

#: Substrings that would betray stored image bytes.
IMAGE_HINTS = (
    "image",
    "photo",
    "screenshot",
    "picture",
    "thumbnail",
    "bytes",
    "blob",
    "base64",
    "_b64",
    "attachment",
    "payload_file",
)
BINARY_TYPE_NAMES = ("LargeBinary", "BINARY", "VARBINARY", "BYTEA", "BLOB", "PickleType")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(hashing.SECRET_ENV, SECRET)


@pytest.fixture
def engine() -> sa.Engine:
    eng = sa.create_engine("sqlite://")

    @sa.event.listens_for(eng, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine: sa.Engine) -> Session:
    with Session(engine) as s:
        yield s


def make_check(**overrides: object) -> Check:
    values: dict = {
        "id": uuid.uuid4(),
        "created_at": datetime.now(UTC),
        "surface": "telegram",
        "input_type": "text",
        "lang": "ru",
        "text_sha256": hashlib.sha256(b"whatever").hexdigest(),
        "text_scrubbed": "Ваша карта заблокирована, назовите код из СМС",
        "verdict": {"band": "scam", "risk": 0.94},
        "playbook_id": "kz.bank_security_call",
        "band": "scam",
        "risk": 0.94,
        "model": "deepseek-chat",
        "latency_ms": 812,
        "actor_hash": hash_actor(404_040_404),
    }
    values.update(overrides)
    return Check(**values)


def migration_sql(monkeypatch: pytest.MonkeyPatch) -> str:
    """The SQL `alembic upgrade head` would run against Postgres."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/saqbol")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.attributes["configure_logger"] = False
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def statements(sql: str) -> list[str]:
    body = re.sub(r"^--.*$", "", sql, flags=re.M)
    return [re.sub(r"\s+", " ", s).strip() for s in body.split(";") if s.strip()]


def all_columns() -> list[tuple[str, sa.Column]]:
    return [(t.name, c) for t in Base.metadata.sorted_tables for c in t.columns]


# --------------------------------------------------------------------------
# the schema is the contract
# --------------------------------------------------------------------------


def test_tables_are_exactly_the_contract():
    assert set(Base.metadata.tables) == set(CONTRACT)


@pytest.mark.parametrize("table", sorted(CONTRACT))
def test_columns_are_exactly_the_contract(table: str):
    assert tuple(c.name for c in Base.metadata.tables[table].columns) == CONTRACT[table]


def test_checks_carries_the_three_contract_indexes():
    names = {i.name for i in Check.__table__.indexes}
    assert names == {"ix_checks_created_at", "ix_checks_text_sha256", "ix_checks_playbook_id"}


def test_playbook_embedding_is_the_retrieval_dimension():
    assert EMBEDDING_DIM == 384
    rendered = str(CreateTable(Playbook.__table__).compile(dialect=postgresql.dialect()))
    assert "VECTOR(384)" in rendered


def test_rate_limit_is_keyed_by_actor_and_day():
    assert [c.name for c in RateLimit.__table__.primary_key] == ["actor_hash", "day"]


def test_stats_daily_holds_counts_only(session: Session):
    session.add(
        StatsDaily(
            day=date(2026, 9, 7),
            checks=120,
            unique_actors=44,
            scam_count=51,
            unsure_count=9,
            top_playbook="kz.bank_security_call",
        )
    )
    session.commit()
    assert session.get(StatsDaily, date(2026, 9, 7)).unique_actors == 44


# --------------------------------------------------------------------------
# 1. no raw identifier reaches the database
# --------------------------------------------------------------------------


def test_no_column_name_suggests_a_raw_identifier():
    offenders = [
        f"{table}.{col.name}"
        for table, col in all_columns()
        if not col.name.endswith(DIGEST_SUFFIXES)
        and any(hint in col.name.lower() for hint in RAW_IDENTIFIER_HINTS)
    ]
    assert offenders == []


def test_migration_creates_no_raw_identifier_column(monkeypatch: pytest.MonkeyPatch):
    sql = migration_sql(monkeypatch).lower()
    for hint in RAW_IDENTIFIER_HINTS:
        assert hint not in sql, f"migration mentions {hint!r}"


def test_actor_columns_exist_and_are_digests():
    assert "actor_hash" in Check.__table__.c
    assert "actor_hash" in RateLimit.__table__.c


def test_hash_actor_is_hmac_of_the_configured_secret():
    expected = hmac.new(SECRET.encode(), b"404040404", hashlib.sha256).hexdigest()
    assert hash_actor(404_040_404) == expected
    assert hash_actor("404040404") == expected
    assert is_actor_hash(expected)


def test_hash_actor_separates_actors():
    assert hash_actor("1.2.3.4") != hash_actor("1.2.3.5")


def test_hash_actor_depends_on_the_secret(monkeypatch: pytest.MonkeyPatch):
    first = hash_actor(777)
    monkeypatch.setenv(hashing.SECRET_ENV, "u" * 48)
    assert hash_actor(777) != first


def test_hashing_refuses_without_a_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(hashing.SECRET_ENV, raising=False)
    with pytest.raises(RuntimeError, match="is not set"):
        hash_actor(1)


def test_hashing_refuses_the_shipped_placeholder(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(hashing.SECRET_ENV, "change_me_to_32_random_bytes")
    with pytest.raises(RuntimeError, match="placeholder"):
        hash_actor(1)


def test_the_env_example_secret_is_one_the_code_rejects(monkeypatch: pytest.MonkeyPatch):
    """Whatever ships in .env.example must not be usable as a real secret."""
    line = next(
        line
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{hashing.SECRET_ENV}=")
    )
    monkeypatch.setenv(hashing.SECRET_ENV, line.split("=", 1)[1])
    with pytest.raises(RuntimeError):
        hashing.actor_secret()


def test_hashing_refuses_a_short_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(hashing.SECRET_ENV, "short")
    with pytest.raises(RuntimeError, match="characters"):
        hash_actor(1)


def test_hash_actor_refuses_an_empty_identifier():
    with pytest.raises(ValueError, match="empty"):
        hash_actor("   ")


@pytest.mark.parametrize(
    "raw",
    ["404040404", "@toktar", "192.0.2.17", "", "a" * 63, "A" * 64, "z" * 64],
)
def test_check_refuses_anything_that_is_not_a_digest(raw: str):
    with pytest.raises(ValueError, match="hash_actor"):
        make_check(actor_hash=raw)


def test_rate_limit_refuses_anything_that_is_not_a_digest():
    with pytest.raises(ValueError, match="hash_actor"):
        RateLimit(actor_hash="404040404", day=date(2026, 9, 8), count=1)


def test_hashed_actor_is_accepted_by_both_tables(session: Session):
    digest = hash_actor(404_040_404)
    session.add(make_check(actor_hash=digest))
    session.add(RateLimit(actor_hash=digest, day=date(2026, 9, 8), count=3))
    session.commit()
    assert session.scalar(sa.select(sa.func.count()).select_from(Check)) == 1


def test_the_database_itself_rejects_a_raw_actor_id(session: Session):
    """Belt and braces: SQL that bypasses the ORM still cannot store a raw id."""
    with pytest.raises(IntegrityError):
        session.execute(
            sa.text(
                "INSERT INTO checks (id, created_at, surface, input_type, lang, text_sha256,"
                " verdict, band, risk, model, latency_ms, consent_dataset, actor_hash)"
                " VALUES ('x', '2026-09-08', 'telegram', 'text', 'ru', 'h', '{}', 'scam',"
                " 0.9, 'm', 10, 0, '404040404')"
            )
        )


# --------------------------------------------------------------------------
# 2. text has a lifetime, and something ends it
# --------------------------------------------------------------------------


def test_text_scrubbed_is_nullable():
    assert Check.__table__.c.text_scrubbed.nullable is True


def test_migration_leaves_text_scrubbed_nullable(monkeypatch: pytest.MonkeyPatch):
    create = next(
        s for s in statements(migration_sql(monkeypatch)) if s.startswith("CREATE TABLE checks")
    )
    assert "text_scrubbed TEXT," in create
    assert "text_scrubbed TEXT NOT NULL" not in create


def test_retention_nulls_expired_text_only(session: Session):
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    stale = make_check(created_at=now - timedelta(days=31), text_scrubbed="старое")
    fresh = make_check(created_at=now - timedelta(days=29), text_scrubbed="свежее")
    session.add_all([stale, fresh])
    session.commit()

    assert purge_expired_text(session, now=now, days=30) == 1
    session.commit()
    session.expire_all()

    assert session.get(Check, stale.id).text_scrubbed is None
    assert session.get(Check, fresh.id).text_scrubbed == "свежее"


def test_retention_keeps_everything_that_is_not_the_text(session: Session):
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    old = make_check(created_at=now - timedelta(days=400))
    session.add(old)
    session.commit()

    purge_expired_text(session, now=now, days=30)
    session.commit()
    session.expire_all()

    row = session.get(Check, old.id)
    assert row.text_scrubbed is None
    assert row.text_sha256 == hashlib.sha256(b"whatever").hexdigest()
    assert row.verdict == {"band": "scam", "risk": 0.94}
    assert row.band == "scam"
    assert is_actor_hash(row.actor_hash)


def test_retention_is_idempotent(session: Session):
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    session.add(make_check(created_at=now - timedelta(days=99)))
    session.commit()

    assert purge_expired_text(session, now=now, days=30) == 1
    session.commit()
    assert purge_expired_text(session, now=now, days=30) == 0


def test_retention_reads_the_window_from_the_environment(
    session: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(retention.RETENTION_ENV, "7")
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    session.add(make_check(created_at=now - timedelta(days=8)))
    session.add(make_check(created_at=now - timedelta(days=6)))
    session.commit()

    assert purge_expired_text(session, now=now) == 1


def test_retention_days_defaults_to_thirty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(retention.RETENTION_ENV, raising=False)
    assert retention_days() == retention.DEFAULT_RETENTION_DAYS == 30


def test_env_example_agrees_with_the_default(monkeypatch: pytest.MonkeyPatch):
    line = next(
        line
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{retention.RETENTION_ENV}=")
    )
    assert int(line.split("=", 1)[1]) == retention.DEFAULT_RETENTION_DAYS


@pytest.mark.parametrize("value", ["nightly", "0", "-1", "30.5"])
def test_retention_days_refuses_nonsense(value: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(retention.RETENTION_ENV, value)
    with pytest.raises(RuntimeError):
        retention_days()


def test_retention_leaves_the_corpus_alone(session: Session):
    """Donated, reviewed rows are the dataset. They are not a byproduct."""
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    session.add(candidate)
    session.commit()

    purge_expired_text(session, now=now, days=1)
    session.commit()
    session.expire_all()

    assert session.get(DatasetCandidate, candidate.id).text_scrubbed == "донат"


def test_retention_dry_run_changes_nothing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert retention.main(["--dry-run", "--days", "30"]) == 0


# --------------------------------------------------------------------------
# 3. no image bytes, anywhere
# --------------------------------------------------------------------------


def test_no_table_has_a_binary_column():
    offenders = [
        f"{table}.{col.name}"
        for table, col in all_columns()
        if isinstance(col.type, sa.LargeBinary) or col.type.__class__.__name__ in BINARY_TYPE_NAMES
    ]
    assert offenders == []


def test_no_column_name_suggests_stored_pixels():
    offenders = [
        f"{table}.{col.name}"
        for table, col in all_columns()
        if any(hint in col.name.lower() for hint in IMAGE_HINTS)
    ]
    assert offenders == []


def test_migration_creates_no_bytes_column(monkeypatch: pytest.MonkeyPatch):
    sql = migration_sql(monkeypatch).lower()
    for spelling in ("bytea", "blob", "binary", "image", "photo", "base64"):
        assert spelling not in sql, f"migration mentions {spelling!r}"


def test_a_screenshot_check_stores_only_its_text(session: Session):
    """T203: the image is analysed, then discarded. Only the OCR text remains."""
    check = make_check(input_type="image", text_scrubbed="Ваш платёж отклонён")
    session.add(check)
    session.commit()

    stored = {c.name for c in Check.__table__.columns}
    assert not stored & {"image", "image_bytes", "screenshot", "photo_b64"}
    assert session.get(Check, check.id).input_type == "image"


# --------------------------------------------------------------------------
# 4. nothing enters the dataset without a reviewer
# --------------------------------------------------------------------------


def test_a_candidate_is_born_pending(session: Session):
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    session.add(candidate)
    session.commit()
    assert candidate.status == STATUS_PENDING


def test_the_column_default_is_pending():
    column = DatasetCandidate.__table__.c.status
    assert column.default.arg == STATUS_PENDING
    assert column.server_default.arg == STATUS_PENDING


def test_migration_defaults_status_to_pending(monkeypatch: pytest.MonkeyPatch):
    create = next(
        s
        for s in statements(migration_sql(monkeypatch))
        if s.startswith("CREATE TABLE dataset_candidates")
    )
    assert "status TEXT DEFAULT 'pending' NOT NULL" in create


@pytest.mark.parametrize("status", [STATUS_APPROVED, STATUS_REJECTED])
def test_a_candidate_cannot_be_inserted_already_decided(session: Session, status: str):
    session.add(DatasetCandidate(text_scrubbed="донат", source="donated", status=status))
    with pytest.raises(ValueError, match="inserted as 'pending'"):
        session.flush()
    session.rollback()


def test_raw_sql_cannot_insert_an_unreviewed_approval(session: Session):
    with pytest.raises(IntegrityError):
        session.execute(
            sa.text(
                "INSERT INTO dataset_candidates (text_scrubbed, source, status)"
                " VALUES ('донат', 'donated', 'approved')"
            )
        )


def test_status_must_be_one_the_contract_knows(session: Session):
    with pytest.raises(IntegrityError):
        session.execute(
            sa.text(
                "INSERT INTO dataset_candidates (text_scrubbed, source, status)"
                " VALUES ('донат', 'donated', 'published')"
            )
        )


def test_approval_records_who_and_when(session: Session):
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    session.add(candidate)
    session.commit()

    candidate.approve("toktar", when=datetime(2026, 9, 8, 9, 30, tzinfo=UTC))
    session.commit()
    session.expire_all()

    stored = session.get(DatasetCandidate, candidate.id)
    assert stored.status == STATUS_APPROVED
    assert stored.reviewer == "toktar"
    assert stored.reviewed_at is not None


def test_rejection_records_a_reason(session: Session):
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    session.add(candidate)
    session.commit()

    candidate.reject("toktar", "duplicate of #41")
    session.commit()

    assert candidate.status == STATUS_REJECTED
    assert candidate.reject_reason == "duplicate of #41"


def test_a_decision_must_name_a_reviewer():
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    with pytest.raises(ValueError, match="name its reviewer"):
        candidate.approve("  ")


def test_a_rejection_must_give_a_reason():
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    with pytest.raises(ValueError, match="needs a reason"):
        candidate.reject("toktar", "  ")


def test_a_decision_is_made_once():
    candidate = DatasetCandidate(text_scrubbed="донат", source="donated")
    candidate.approve("toktar")
    with pytest.raises(ValueError, match="already approved"):
        candidate.reject("someone-else", "second thoughts")


def test_a_press_row_must_cite_its_source(session: Session):
    session.add(DatasetCandidate(text_scrubbed="из газеты", source="press"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(
        DatasetCandidate(
            text_scrubbed="из газеты", source="press", source_url="https://example.kz/a"
        )
    )
    session.commit()


def test_feedback_follows_its_check_into_the_grave(session: Session):
    check = make_check()
    session.add(check)
    session.commit()
    session.add(Feedback(check_id=check.id, was_correct=False, comment="это был мой банк"))
    session.commit()

    session.delete(check)
    session.commit()

    assert session.scalar(sa.select(sa.func.count()).select_from(Feedback)) == 0


# --------------------------------------------------------------------------
# the migration and the models describe the same database
# --------------------------------------------------------------------------


def test_there_is_exactly_one_migration_head():
    script = ScriptDirectory(str(ROOT / "alembic"))
    assert len(script.get_heads()) == 1


def test_migration_creates_the_pgvector_extension(monkeypatch: pytest.MonkeyPatch):
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration_sql(monkeypatch)


def test_migration_creates_the_hnsw_index(monkeypatch: pytest.MonkeyPatch):
    sql = migration_sql(monkeypatch)
    assert "USING hnsw (embedding vector_cosine_ops)" in sql


def test_migration_and_models_emit_identical_ddl(monkeypatch: pytest.MonkeyPatch):
    """The only offline defence against a model that drifted from its migration."""
    dialect = postgresql.dialect()
    expected: dict[tuple[str, str], str] = {}
    for table in Base.metadata.sorted_tables:
        expected["table", table.name] = re.sub(
            r"\s+", " ", str(CreateTable(table).compile(dialect=dialect))
        ).strip()
        for index in table.indexes:
            expected["index", index.name] = re.sub(
                r"\s+", " ", str(CreateIndex(index).compile(dialect=dialect))
            ).strip()

    produced: dict[tuple[str, str], str] = {}
    for statement in statements(migration_sql(monkeypatch)):
        if match := re.match(r"CREATE TABLE (\w+)", statement):
            produced["table", match.group(1)] = statement
        elif match := re.match(r"CREATE INDEX (\w+)", statement):
            produced["index", match.group(1)] = statement
    produced.pop(("table", "alembic_version"), None)

    assert produced == expected


# --------------------------------------------------------------------------
# real Postgres
# --------------------------------------------------------------------------


def postgres_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a Postgres server")
    return url


@pytest.fixture
def pg_engine() -> sa.Engine:
    eng = sa.create_engine(postgres_url())
    try:
        with eng.connect():
            pass
    except sa.exc.OperationalError as exc:  # pragma: no cover - depends on the host
        pytest.skip(f"Postgres unreachable: {exc}")
    return eng


@pytest.mark.network
def test_migration_applies_to_postgres_and_leaves_no_diff(pg_engine: sa.Engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")

    with pg_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = [d for d in compare_metadata(context, Base.metadata) if _touches_our_tables(d)]
    assert diff == []


def _touches_our_tables(diff: object) -> bool:
    return any(name in str(diff) for name in CONTRACT)


@pytest.mark.network
def test_pgvector_extension_is_installed(pg_engine: sa.Engine):
    with pg_engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        )


@pytest.mark.network
def test_embedding_round_trips_and_ranks_by_cosine_distance(pg_engine: sa.Engine):
    near = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    far = [0.0] * (EMBEDDING_DIM - 1) + [1.0]

    # Nothing is committed: the rows exist for the length of the transaction.
    with Session(pg_engine) as session:
        session.add_all(
            [
                Playbook(id="test.near", version=1, content={}, embedding=near),
                Playbook(id="test.far", version=1, content={}, embedding=far),
            ]
        )
        session.flush()

        ranked = session.scalars(
            sa.select(Playbook.id)
            .where(Playbook.id.like("test.%"))
            .order_by(Playbook.embedding.cosine_distance(near))
        ).all()
        stored = session.get(Playbook, "test.near")
        assert len(stored.embedding) == EMBEDDING_DIM
        assert ranked == ["test.near", "test.far"]
        session.rollback()


@pytest.mark.network
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_retention_and_money_on_postgres(pg_engine: sa.Engine):
    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        stale = make_check(created_at=now - timedelta(days=90), cost_usd=Decimal("0.000412"))
        session.add(stale)
        session.flush()

        assert purge_expired_text(session, now=now, days=30) >= 1
        session.expire_all()
        row = session.get(Check, stale.id)
        assert row.text_scrubbed is None
        assert row.cost_usd == Decimal("0.000412")
        assert row.created_at.tzinfo is not None
        session.rollback()
