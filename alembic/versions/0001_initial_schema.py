"""Initial schema: checks, feedback, dataset candidates, playbooks, limits, stats

Mirrors docs/02_DATA_CONTRACTS.md section 4 and src/saqbol/db/models.py.

Types are spelled out rather than imported from the models, so that this
revision keeps describing the database it actually created even after the
models move on.

Revision ID: 0001
Revises:
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Must match saqbol.db.base.EMBEDDING_DIM.
EMBEDDING_DIM = 384

#: HMAC-SHA256, lowercase hex. Enforced in the database as well as the ORM so
#: that a raw Telegram id cannot be inserted by any route.
DIGEST_LENGTH = 64


def upgrade() -> None:
    # pgvector must exist before the playbooks table references its type.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("input_type", sa.Text(), nullable=False),
        sa.Column("lang", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        # Nullable by design: the retention job empties it. See
        # saqbol.db.retention.purge_expired_text.
        sa.Column("text_scrubbed", sa.Text(), nullable=True),
        sa.Column("verdict", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=True),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column("risk", sa.REAL(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("consent_dataset", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("actor_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(f"length(actor_hash) = {DIGEST_LENGTH}", name="actor_hash_is_digest"),
        sa.PrimaryKeyConstraint("id", name="pk_checks"),
    )
    op.create_index("ix_checks_created_at", "checks", ["created_at"])
    op.create_index("ix_checks_text_sha256", "checks", ["text_sha256"])
    op.create_index("ix_checks_playbook_id", "checks", ["playbook_id"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("check_id", sa.Uuid(), nullable=True),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["check_id"],
            ["checks.id"],
            name="fk_feedback_check_id_checks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
    )

    op.create_table(
        "dataset_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("check_id", sa.Uuid(), nullable=True),
        sa.Column("text_scrubbed", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        # Every row starts here. Approval is a reviewed transition, not an insert.
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="status_known",
        ),
        sa.CheckConstraint(
            "source <> 'press' OR source_url IS NOT NULL",
            name="press_needs_source_url",
        ),
        sa.CheckConstraint(
            "status = 'pending' OR (reviewer IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="decided_rows_are_reviewed",
        ),
        sa.ForeignKeyConstraint(
            ["check_id"], ["checks.id"], name="fk_dataset_candidates_check_id_checks"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_candidates"),
    )

    op.create_table(
        "playbooks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_playbooks"),
    )
    op.create_index(
        "ix_playbooks_embedding_hnsw",
        "playbooks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "rate_limits",
        sa.Column("actor_hash", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(f"length(actor_hash) = {DIGEST_LENGTH}", name="actor_hash_is_digest"),
        sa.PrimaryKeyConstraint("actor_hash", "day", name="pk_rate_limits"),
    )

    op.create_table(
        "stats_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("checks", sa.Integer(), nullable=False),
        sa.Column("unique_actors", sa.Integer(), nullable=False),
        sa.Column("scam_count", sa.Integer(), nullable=False),
        sa.Column("unsure_count", sa.Integer(), nullable=False),
        sa.Column("top_playbook", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("day", name="pk_stats_daily"),
    )


def downgrade() -> None:
    op.drop_table("stats_daily")
    op.drop_table("rate_limits")
    op.drop_index("ix_playbooks_embedding_hnsw", table_name="playbooks")
    op.drop_table("playbooks")
    op.drop_table("dataset_candidates")
    op.drop_table("feedback")
    op.drop_index("ix_checks_playbook_id", table_name="checks")
    op.drop_index("ix_checks_text_sha256", table_name="checks")
    op.drop_index("ix_checks_created_at", table_name="checks")
    op.drop_table("checks")
    # The vector extension is left in place. It may predate this migration and
    # may be shared with other schemas; dropping it is not the inverse of
    # CREATE EXTENSION IF NOT EXISTS.
