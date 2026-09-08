"""Engine and session construction.

There is no settings object in this codebase; modules read the environment at
the point of use (see core/llm.py). This one does the same, and refuses to
guess a connection string, because the default that would be guessed is a
developer's laptop and the caller would be a nightly job.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

URL_ENV = "DATABASE_URL"


def database_url() -> str:
    url = os.environ.get(URL_ENV, "").strip()
    if not url:
        raise RuntimeError(f"{URL_ENV} is not set. See .env.example.")
    return url


def build_engine(url: str | None = None, **kwargs: object) -> Engine:
    return create_engine(url or database_url(), **kwargs)


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """A session that commits on success and rolls back on anything else."""
    session = build_sessionmaker(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
