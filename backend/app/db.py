"""SQLAlchemy engine, session factory, and declarative Base.

One engine per process. Sessions are short-lived and per-request.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


# Pool sizing is Postgres-only; SQLite (used by tests) doesn't accept it.
# SQLite + FastAPI TestClient cross threads, so check_same_thread=False is
# required there. The dialect-keyed branching keeps prod code postgres-only.
_pg = settings.database_url.startswith("postgresql")
if _pg:
    # Sized for the poster-storm fan-out: a full library grid load issues one
    # authenticated request per poster, each checking out a connection through
    # current_user. 20 persistent + 30 overflow gives 50 for the API. Stream
    # runs in a separate process with its own (mostly idle) pool, and Postgres
    # max_connections is 100, so the combined realistic peak stays well under
    # the ceiling. pool_timeout=10 makes a genuinely saturated pool fail fast
    # instead of hanging a request for the 30s default.
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        pool_timeout=10,
        future=True,
    )
else:
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    """Declarative base. All models inherit from this."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Yields a session, closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context-manager form for scripts and background jobs."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
