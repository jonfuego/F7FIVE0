"""Regression test for the 2026-08-08 poster-storm pool exhaustion.

A full library grid load fans out one authenticated request per poster.
Before the fix, a hundred-plus concurrent poster reads exhausted the DB
connection pool (`pool_size=5` + `max_overflow=10`) and the remainder
queued for the 30s timeout and 500'd. This fires a burst of concurrent
authenticated requests at the art read endpoint and asserts that none come
back 5xx, which is how a pool timeout surfaces.

The shared conftest fixtures back the app with an in-memory SQLite
`StaticPool`: one connection, not thread-safe, so it can't model a
concurrent burst. This module stands up its own file-backed SQLite engine
with a real `QueuePool` (each pooled connection independent) so 60 threads
genuinely contend for a bounded pool, mirroring the production shape.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

# Comfortably above the incident's fan-out floor and the criterion's minimum.
_CONCURRENCY = 60


@pytest.fixture()
def pooled_client(engine, tmp_path):
    """A TestClient whose get_db draws from a real thread-safe pool.

    Depends on the session-scoped `engine` fixture only to guarantee the
    models are imported and the Postgres-only server defaults are stripped
    off `Base.metadata` before we create_all against our own engine.
    """
    from app.api.deps import current_user, get_db
    from app.db import Base
    from app.main import app
    from app.models.user import User

    db_path = tmp_path / "pool_pressure.db"
    test_engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=10,
        future=True,
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    fake_admin = User(
        id=uuid.uuid4(),
        username="pool-admin",
        display_name="Pool Admin",
        password_hash="x",
        role="admin",
        is_active=True,
    )

    def _override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    def _override_user():
        return fake_admin

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = _override_user
    try:
        c = TestClient(app)
        yield c
        c.close()
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()


def test_art_endpoint_survives_poster_burst(pooled_client):
    """60 concurrent authenticated art reads, zero 5xx responses."""
    # A valid (kind, role) pair with no override row -> the endpoint runs the
    # full auth + db path and returns a clean 404, never a 5xx.
    paths = [
        f"/api/art/movie/{uuid.uuid4()}/poster"
        for _ in range(_CONCURRENCY)
    ]

    def _get(path: str) -> int:
        return pooled_client.get(path).status_code

    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
        statuses = list(pool.map(_get, paths))

    assert len(statuses) == _CONCURRENCY
    server_errors = [s for s in statuses if s >= 500]
    assert not server_errors, f"pool pressure produced 5xx responses: {server_errors}"
