"""Auth events fit `auth_events.event` and an audit failure never fails a request.

Admin > Users > Disable once answered HTTP 500 on PostgreSQL because the event
`admin_updated_user:<uuid>:is_active` was 65 characters and the column is
`String(64)`. SQLite (these tests) does not enforce column lengths, so the
length is checked here against the model's own column length, using the same
builders the code calls.
"""
from __future__ import annotations

import ast
import itertools
import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select

from app.models.user import AuthEvent, Session as UserSession, User, UserRole
from app.services import auth_events

APP_DIR = Path(auth_events.__file__).resolve().parent.parent
FULL_UUID = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")  # 36 characters

# Calls that write an audit row, and where their `event` argument sits when it
# is passed by position (all of them also accept `event=`).
WRITER_EVENT_POSITION = {
    "_log_auth_event": None,
    "_audit": 2,
    "_audit_event": 2,
    "record_auth_event": None,
}


def _is_named_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))


def column_limit() -> int:
    return AuthEvent.__table__.c.event.type.length


def all_builder_events() -> list[str]:
    """Every string a builder in services/auth_events.py can produce."""
    events: list[str] = []
    fields = list(auth_events.USER_FIELD_CODES)
    # update_user adds fields in this order, so every subset in order.
    for n in range(1, len(fields) + 1):
        for combo in itertools.combinations(fields, n):
            events.append(auth_events.admin_updated_user(FULL_UUID, combo))
    events.append(auth_events.admin_created_user(FULL_UUID))
    events.append(auth_events.admin_reset_password(FULL_UUID))
    for client_type in auth_events.PASSKEY_CLIENT_TYPES:
        events.append(auth_events.passkey_login(client_type))
    return events


# ---------------------------------------------------------------------------
# Length
# ---------------------------------------------------------------------------
def test_event_limit_comes_from_the_model_column():
    assert column_limit() == auth_events.EVENT_MAX_LEN
    assert column_limit() >= 64  # the migrated PostgreSQL column is String(64)


def test_every_builder_event_fits_the_event_column():
    limit = column_limit()
    events = all_builder_events()
    assert len(events) >= 10
    too_long = [(len(e), e) for e in events if len(e) > limit]
    assert not too_long, f"events longer than {limit}: {too_long}"


def test_longest_update_user_event_fits_with_a_full_uuid():
    fields = list(auth_events.USER_FIELD_CODES)
    longest = auth_events.admin_updated_user(FULL_UUID, fields)
    assert str(FULL_UUID) in longest  # target user id stays recoverable
    assert len(longest) <= column_limit()
    # The case that broke: is_active alone with a full uuid.
    assert len(auth_events.admin_updated_user(FULL_UUID, ["is_active"])) <= column_limit()


def test_update_user_event_keeps_target_id_and_changed_fields():
    ev = auth_events.admin_updated_user(FULL_UUID, ["role", "is_active"])
    assert ev == f"user_edit:{FULL_UUID}:role+active"


def test_every_event_literal_in_the_source_fits_and_none_is_built_inline():
    """Walk backend/app: each audit write passes a short literal or a builder
    from services/auth_events.py. A new f-string event fails here."""
    limit = column_limit()
    builders = {
        name for name, obj in vars(auth_events).items()
        if callable(obj) and getattr(obj, "__module__", "") == auth_events.__name__
        and not name.startswith("_")
    }
    problems: list[str] = []
    seen_literals: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not _is_named_call(node):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name == "AuthEvent" and path.name != "auth_events.py":
                problems.append(f"{path.name}:{node.lineno} builds AuthEvent directly")
                continue
            if name not in WRITER_EVENT_POSITION:
                continue
            arg = next((k.value for k in node.keywords if k.arg == "event"), None)
            pos = WRITER_EVENT_POSITION[name]
            if arg is None and pos is not None and len(node.args) > pos:
                arg = node.args[pos]
            if arg is None:
                problems.append(f"{path.name}:{node.lineno} {name}() has no event argument")
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                seen_literals.append(arg.value)
                if len(arg.value) > limit:
                    problems.append(f"{path.name}:{node.lineno} literal too long: {arg.value}")
            elif (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and isinstance(arg.func.value, ast.Name)
                and arg.func.value.id == "auth_events"
                and arg.func.attr in builders
            ):
                continue
            elif isinstance(arg, ast.Name) and arg.id == "event":
                continue  # a thin wrapper passing its own `event` parameter on
            else:
                problems.append(
                    f"{path.name}:{node.lineno} event is not a literal or an "
                    f"auth_events builder: {ast.dump(arg)[:60]}"
                )
    assert not problems, "\n".join(problems)
    assert "login_success" in seen_literals  # the walk really found call sites


def test_fit_event_never_returns_more_than_the_column_holds():
    long_one = "x" * (column_limit() + 30)
    assert len(auth_events.fit_event(long_one)) == column_limit()
    assert auth_events.fit_event("login_success") == "login_success"


# ---------------------------------------------------------------------------
# End to end through the real endpoint
# ---------------------------------------------------------------------------
def _member(db, name="target", *, role="member", active=True) -> User:
    u = User(
        username=name, display_name=name.title(), password_hash="x",
        role=role, is_active=active,
    )
    db.add(u)
    db.commit()
    return u


def _events(db) -> list[str]:
    db.expire_all()
    return [e.event for e in db.scalars(select(AuthEvent))]


def test_disable_enable_and_role_change_work_and_log_short_events(client, db_session):
    target = _member(db_session)
    url = f"/api/auth/users/{target.id}"

    r = client.patch(url, json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    r = client.patch(url, json={"is_active": True})
    assert r.status_code == 200 and r.json()["is_active"] is True

    r = client.patch(url, json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"

    # Everything at once: the longest combination update_user can produce.
    r = client.patch(url, json={
        "display_name": "Renamed", "role": "member", "is_active": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is False and body["role"] == "member"

    events = _events(db_session)
    edits = [e for e in events if e.startswith("user_edit:")]
    assert len(edits) == 4
    assert all(len(e) <= column_limit() for e in events)
    assert all(str(target.id) in e for e in edits)
    assert any(e.endswith(":name+role+active") for e in edits)


def test_disable_revokes_the_users_sessions(client, db_session, active_session):
    target, sess = active_session()
    r = client.patch(f"/api/auth/users/{target.id}", json={"is_active": False})
    assert r.status_code == 200
    db_session.expire_all()
    assert db_session.get(UserSession, sess.id).revoked_at is not None


def test_create_and_reset_password_events_fit(client, db_session):
    r = client.post("/api/auth/users", json={
        "username": "newbie", "display_name": "New", "password": "longenoughpw1",
        "role": "member",
    })
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = client.post(f"/api/auth/users/{uid}/password", json={"new_password": "anotherlongpw2"})
    assert r.status_code == 204, r.text
    events = _events(db_session)
    assert any(e.startswith("admin_created_user:") for e in events)
    assert any(e.startswith("admin_reset_password:") for e in events)
    assert all(len(e) <= column_limit() for e in events)


# ---------------------------------------------------------------------------
# A failing audit write never fails the request
# ---------------------------------------------------------------------------
def _break_insert(monkeypatch):
    """The audit row now violates NOT NULL, so the INSERT is rejected by the
    database (a real statement failure, like PostgreSQL's length error)."""
    real = auth_events._build_row

    def bad(**kw):
        row = real(**kw)
        row.event = None
        return row

    monkeypatch.setattr(auth_events, "_build_row", bad)


def _break_build(monkeypatch):
    def boom(**_kw):
        raise RuntimeError("audit exploded")

    monkeypatch.setattr(auth_events, "_build_row", boom)


@pytest.mark.parametrize("breaker", [_break_insert, _break_build])
def test_failed_audit_write_does_not_fail_admin_disable(
    client, db_session, monkeypatch, caplog, breaker,
):
    target = _member(db_session)
    breaker(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=auth_events.__name__):
        r = client.patch(f"/api/auth/users/{target.id}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    # The change really committed, and the session is still usable afterwards.
    db_session.expire_all()
    assert db_session.get(User, target.id).is_active is False
    assert not [e for e in _events(db_session) if e.startswith("user_edit:")]

    msgs = [rec.getMessage() for rec in caplog.records if "audit write failed" in rec.getMessage()]
    assert msgs, "the swallowed failure must be logged"
    assert "user_edit:" in msgs[0]


def test_failed_audit_insert_is_rolled_back_in_a_savepoint(
    client, db_session, engine, monkeypatch,
):
    """The failed INSERT must be undone by ROLLBACK TO SAVEPOINT, not by
    aborting the surrounding transaction (which is what PostgreSQL would do to
    a bare failed statement)."""
    target = _member(db_session)
    _break_insert(monkeypatch)
    statements: list[str] = []

    @sa_event.listens_for(engine, "before_cursor_execute")
    def _spy(_conn, _cursor, statement, *_a):  # noqa: ANN001
        statements.append(statement.strip().upper().split("\n")[0])

    try:
        r = client.patch(f"/api/auth/users/{target.id}", json={"role": "admin"})
    finally:
        sa_event.remove(engine, "before_cursor_execute", _spy)
    assert r.status_code == 200, r.text
    assert any(s.startswith("SAVEPOINT") for s in statements)
    assert any(s.startswith("ROLLBACK TO SAVEPOINT") for s in statements)
    db_session.expire_all()
    assert db_session.get(User, target.id).role.value == "admin"


def test_failed_audit_write_does_not_fail_login(db_session, monkeypatch):
    """Same guarantee on the unauthenticated path: login still answers."""
    from fastapi.testclient import TestClient
    from app.db import get_db
    from app.main import app
    from app.services.security import hash_password

    u = User(
        username="auditproof", display_name="A", password_hash=hash_password("hunter2password"),
        role=UserRole.member, is_active=True,
    )
    db_session.add(u)
    db_session.commit()

    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    _break_insert(monkeypatch)
    try:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": "auditproof", "password": "hunter2password"})
        c.close()
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
