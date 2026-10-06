"""Saved library views, per user on the server (batch 3 item 8)."""
from __future__ import annotations

import uuid

import pytest

from app.api.deps import current_user
from app.api.view_prefs import MAX_VALUE_BYTES
from app.main import app
from app.models.user import User


def _user(db_session, name: str) -> User:
    u = User(id=uuid.uuid4(), username=name, display_name=name, password_hash="x",
             role="member", is_active=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def two_users(client, db_session):
    a = _user(db_session, "alice")
    b = _user(db_session, "bob")
    state = {"who": a}
    app.dependency_overrides[current_user] = lambda: state["who"]

    def as_user(u):
        state["who"] = u

    return a, b, as_user


def test_round_trip(client, two_users):
    a, _b, as_user = two_users
    as_user(a)
    assert client.get("/api/view-prefs").json() == {"prefs": {}}

    r = client.put("/api/view-prefs/music.browse", json={"value": "albums"})
    assert r.status_code == 200, r.text
    assert r.json()["key"] == "music.browse"
    assert r.json()["value"] == "albums"

    sort = {"sortKey": "year", "dir": "desc", "filterKey": None}
    assert client.put("/api/view-prefs/sort:movies", json={"value": sort}).status_code == 200
    # Overwrite keeps one row per key.
    assert client.put("/api/view-prefs/music.browse", json={"value": "songs"}).status_code == 200

    assert client.get("/api/view-prefs").json() == {
        "prefs": {"music.browse": "songs", "sort:movies": sort},
    }


def test_users_do_not_see_each_others_views(client, two_users):
    a, b, as_user = two_users
    as_user(a)
    client.put("/api/view-prefs/music.browse", json={"value": "albums"})
    as_user(b)
    assert client.get("/api/view-prefs").json() == {"prefs": {}}
    client.put("/api/view-prefs/music.browse", json={"value": "songs"})
    as_user(a)
    assert client.get("/api/view-prefs").json()["prefs"]["music.browse"] == "albums"
    as_user(b)
    assert client.get("/api/view-prefs").json()["prefs"]["music.browse"] == "songs"


@pytest.mark.parametrize("key", [
    "Music.Browse",      # uppercase
    "-starts-with-dash",
    "has space",
    "semi;colon",
    "x" * 65,            # too long
    "slash%2Fpath",
])
def test_bad_key_rejected(client, two_users, key):
    a, _b, as_user = two_users
    as_user(a)
    r = client.put(f"/api/view-prefs/{key}", json={"value": "albums"})
    assert r.status_code in (404, 422), (key, r.status_code)
    assert client.get("/api/view-prefs").json() == {"prefs": {}}


def test_oversized_value_rejected(client, two_users):
    a, _b, as_user = two_users
    as_user(a)
    big = "x" * (MAX_VALUE_BYTES + 1)
    r = client.put("/api/view-prefs/mixes.inputs", json={"value": big})
    assert r.status_code == 413
    assert r.json()["detail"] == "view_value_too_large"
    assert client.get("/api/view-prefs").json() == {"prefs": {}}
    # Right at the cap is fine.
    ok = "x" * (MAX_VALUE_BYTES - 2)  # the JSON quotes make it MAX_VALUE_BYTES
    assert client.put("/api/view-prefs/mixes.inputs", json={"value": ok}).status_code == 200


def test_null_value_rejected(client, two_users):
    a, _b, as_user = two_users
    as_user(a)
    assert client.put("/api/view-prefs/music.browse", json={"value": None}).status_code == 422
