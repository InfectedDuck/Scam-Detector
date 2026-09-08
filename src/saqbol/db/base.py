"""Declarative base and the portable column types the models are built from.

The production database is PostgreSQL with pgvector. The schema tests run on
SQLite so CI needs no service container, which means every column type used
here has to compile on both dialects. `with_variant` is how that is done: the
Postgres spelling is authoritative and SQLite gets the nearest equivalent.

The variants are structural, not semantic. On SQLite an embedding is a JSON
array and the HNSW index degrades to an ordinary one, so the schema can be
asserted offline while anything that depends on real vector distance is a
Postgres-only test.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Integer, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON

#: Dimension of the sentence-transformer used for playbook retrieval.
#: Changing it is a migration, not an edit.
EMBEDDING_DIM = 384

#: Explicit constraint names, so a migration can drop a constraint by name
#: rather than by whatever the database happened to call it.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: JSONB on Postgres, plain JSON on SQLite.
JSONColumn = JSON().with_variant(JSONB(), "postgresql")

#: BIGSERIAL on Postgres. SQLite only auto-increments a column declared
#: exactly INTEGER PRIMARY KEY, so it gets INTEGER there.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")

#: VECTOR(384) on Postgres, an inert JSON array on SQLite.
EmbeddingColumn = Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
