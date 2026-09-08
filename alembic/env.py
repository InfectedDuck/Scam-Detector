"""Alembic environment.

Two deviations from the generated default, both deliberate:

* the URL comes from DATABASE_URL rather than alembic.ini, so credentials are
  never in the repository;
* `compare_type` is on, because the difference between VECTOR(384) and
  VECTOR(768) is a silently broken retrieval index rather than an error.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from saqbol.db.base import Base
from saqbol.db.session import database_url

# Importing the models is what populates Base.metadata for autogenerate.
import saqbol.db.models  # noqa: F401  isort:skip

config = context.config

# `configure_logger` lets the schema tests drive alembic in-process without
# fileConfig tearing down pytest's logging.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
