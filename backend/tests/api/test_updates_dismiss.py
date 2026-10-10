"""Admin > Updates: the dismissed update-run id is saved on the server
(app_settings update_run_dismissed) so Dismiss sticks across reloads, browsers
and other admins (punch-list item 4). The endpoint is admin-only.
"""
from __future__ import annotations

import uuid

import pytest

from app.api import admin as admin_routes
from app.api.deps import current_user, require_admin
from app.main import app
from app.models.user import User
from app.services import app_settings


def test_dismiss_defaults_to_none(client):
    r = client.get("/api/admin/updates/dismissed")
    assert r.status_code == 200, r.text
    assert r.json() == {"run_id": None}


def test_dismiss_round_trips_through_app_settings(client, db_session):
    run_id = uuid.uuid4().hex
    r = client.put("/api/admin/updates/dismissed", json={"run_id": run_id})
    assert r.status_code == 200, r.text
    assert r.json() == {"run_id": run_id}

    # Stored under the documented app_settings key, not per-browser state.
    assert app_settings.get(db_session, "update_run_dismissed") == {"run_id": run_id}

    # A fresh read (new "page load") still sees it.
    assert client.get("/api/admin/updates/dismissed").json() == {"run_id": run_id}


def test_dismiss_can_be_cleared(client):
    client.put("/api/admin/updates/dismissed", json={"run_id": "abc123"})
    r = client.put("/api/admin/updates/dismissed", json={"run_id": None})
    assert r.status_code == 200, r.text
    assert r.json() == {"run_id": None}
    assert client.get("/api/admin/updates/dismissed").json() == {"run_id": None}


def test_dismiss_is_admin_only(client, db_session):
    """A member is refused by the real require_admin dependency."""
    member = User(
        id=uuid.uuid4(), username="member-u", display_name="Member",
        password_hash="x", role="member", is_active=True,
    )
    db_session.add(member)
    db_session.commit()

    # Put the real require_admin back (the client fixture stubs it to an admin)
    # and sign in as the member, so the role check actually runs.
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides[current_user] = lambda: member
    try:
        assert client.get("/api/admin/updates/dismissed").status_code == 403
        assert client.put("/api/admin/updates/dismissed", json={"run_id": "x"}).status_code == 403
    finally:
        app.dependency_overrides[require_admin] = lambda: member  # restored by fixture teardown anyway


# Keep the import used so linters don't flag it; admin_routes documents origin.
_ = admin_routes
