"""Shared pytest fixtures.

The repo's tests run against an in-memory SQLite database. The Postgres
JSONB / UUID type columns degrade cleanly enough on SQLite (UUID falls
back to CHAR via SQLAlchemy's generic Uuid; JSONB falls back to JSON)
that the schema can be created by `Base.metadata.create_all` without a
running Postgres.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Required env vars for app.config.Settings. Set BEFORE importing the app.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("STREAM_HMAC_SECRET", "test-stream-secret")

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402


# Map Postgres-only types to SQLite-compatible compilations so create_all
# can build the schema in-memory. Tests don't exercise JSONB-aware
# operators; storage/retrieval as JSON text is sufficient.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(36)"


@compiles(INET, "sqlite")
def _compile_inet_sqlite(_type, _compiler, **_kw):
    return "VARCHAR(45)"


@pytest.fixture(scope="session")
def engine():
    """Reuse the singleton engine that app.db built. SQLite in-memory."""
    import app.models  # noqa: F401  registers all models on Base.metadata
    from sqlalchemy.schema import DefaultClause
    from app.db import Base, engine as _engine

    import re

    @event.listens_for(_engine, "connect")
    def _enable_fk(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

        # Register a `regexp_replace` UDF so the `_sort_expr` helper works
        # on SQLite. Postgres ships it natively; SQLite doesn't.
        def _regexp_replace(value, pattern, replacement, flags=""):
            if value is None:
                return None
            re_flags = re.IGNORECASE if "i" in (flags or "") else 0
            return re.sub(pattern, replacement, value, flags=re_flags)

        dbapi_connection.create_function(
            "regexp_replace", 4, _regexp_replace,
        )

    # Strip Postgres-specific server defaults (`'[]'::jsonb`,
    # `gen_random_uuid()`) so SQLite create_all doesn't choke. Tests
    # don't depend on server-side defaults; ORM-side defaults still fire.
    for table in Base.metadata.tables.values():
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            text = getattr(getattr(sd, "arg", None), "text", "") or ""
            if "::" in text or "gen_random_uuid" in text:
                col.server_default = None

    Base.metadata.create_all(_engine)
    return _engine


@pytest.fixture()
def db_session(engine) -> Session:
    """One session per test, with truncate-based cleanup at teardown.

    StaticPool sharing means we can't use the savepoint-rollback pattern
    cleanly, so we just wipe all rows after each test. SQLite DELETEs are
    fast enough for this scale.
    """
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Wipe data, preserving schema. Iterate in reverse FK dependency
        # order so DELETEs don't tickle the FK constraint.
        from app.db import Base

        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


def make_active_session(db, user=None, *, client_type="browser",
                        revoked=False, rotated=False, expired=False):
    """Create a user (if not given) and a sessions row, returning (user, session).

    SEC-P1-2: signed URLs carry the issuing session id and the serve side checks
    the session is live, so tests that mint and then fetch a signed URL need a
    real session. `rotated` stamps revoked_at AND rotated_at (a token refresh,
    still authorizes its URLs); `revoked` stamps revoked_at only (a real
    logout/revoke, dead); `expired` sets expires_at in the past.
    """
    from app.models.user import Session as UserSession, User

    if user is None:
        user = User(
            username=f"u-{uuid.uuid4().hex[:8]}", display_name="U",
            password_hash="x", role="member", is_active=True,
        )
        db.add(user)
        db.flush()
    now = datetime.now(timezone.utc)
    sess = UserSession(
        user_id=user.id,
        refresh_token_hash=uuid.uuid4().hex,
        client_type=client_type,
        last_seen_at=now,
        expires_at=(now - timedelta(hours=1)) if expired else (now + timedelta(days=30)),
    )
    if rotated:
        sess.revoked_at = now
        sess.rotated_at = now
    elif revoked:
        sess.revoked_at = now
    db.add(sess)
    db.commit()
    return user, sess


@pytest.fixture()
def active_session(db_session: Session):
    """Factory: active_session(**flags) -> (user, session). See make_active_session."""
    def _make(**kw):
        return make_active_session(db_session, **kw)
    return _make


@pytest.fixture()
def client(db_session: Session):
    """FastAPI TestClient with a synthetic admin and the test session."""
    from fastapi.testclient import TestClient

    from app.api.deps import current_session_id, current_user, get_db, require_admin
    from app.main import app
    from app.models.user import User

    fake_admin = User(
        id=uuid.uuid4(),
        username="test-admin",
        display_name="Test Admin",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    # Persist the admin + an active session so mint endpoints have a real
    # session id (SEC-P1-2) and a signed URL minted here survives the serve-side
    # session check.
    db_session.add(fake_admin)
    db_session.flush()
    _admin_session = make_active_session(db_session, user=fake_admin)[1]

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    def _override_user():
        return fake_admin

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = _override_user
    app.dependency_overrides[require_admin] = _override_user
    app.dependency_overrides[current_session_id] = lambda: _admin_session.id
    # Skip the lifespan startup/shutdown: it would dispose the engine on
    # exit and kill the StaticPool connection the db_session fixture is
    # still bound to.
    try:
        c = TestClient(app)
        yield c
        c.close()
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_tmdb_key_cache():
    """The saved TMDB key is cached per process; start each test clean."""
    from app.services import tmdb_key
    tmdb_key.reset_cache()
    yield
    tmdb_key.reset_cache()


@pytest.fixture(autouse=True)
def _keyless_art_sources_off(monkeypatch):
    """No test reaches a real art service. Deezer and TheAudioDB are off unless
    a test turns them on (and then mocks the HTTP itself)."""
    from app.config import settings
    monkeypatch.setattr(settings, "deezer_enabled", False)
    monkeypatch.setattr(settings, "audiodb_api_key", "")
    yield
