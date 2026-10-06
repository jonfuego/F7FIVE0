"""SEC-P1-2: signed URLs are bound to the issuing session.

Covers the two URL kinds not exercised elsewhere (subtitle, download) for the
revoked-session 403, and proves a bad signature is rejected before the session
DB lookup ever runs. The stream and art kinds are covered in
test_track_selection_on_deck.py and test_art_signed.py.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app import stream as gw
from app.api.deps import get_db
from app.main import app
from app.services import security
from tests.conftest import make_active_session


@pytest.fixture()
def api(db_session):
    def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    try:
        yield c, db_session
    finally:
        c.close()
        app.dependency_overrides.clear()


def test_subtitle_revoked_session_403(api):
    c, db = api
    user, sess = make_active_session(db, revoked=True)
    mid = uuid.uuid4()
    p = security.sign_media_url_params(mid, "subtitle", "2", user.id, sess.id)
    r = c.get(
        f"/api/media-files/{mid}/subtitles/2.vtt",
        params={"uid": p["uid"], "sid": p["sid"], "exp": p["exp"], "sig": p["sig"]},
    )
    assert r.status_code == 403


def test_download_revoked_session_403(api):
    c, db = api
    user, sess = make_active_session(db, revoked=True)
    mid = uuid.uuid4()
    p = security.sign_media_url_params(mid, "download", "original", user.id, sess.id)
    r = c.get(
        f"/api/media-files/{mid}/download",
        params={"quality": "original", "uid": p["uid"], "sid": p["sid"],
                "exp": p["exp"], "sig": p["sig"]},
    )
    assert r.status_code == 403


def test_bad_signature_skips_session_db_lookup(db_session, monkeypatch):
    """A bad signature is rejected before the session is looked up (HMAC before
    DB). We track calls to session_authorizes and assert it never fires."""
    calls = {"n": 0}

    def _tracked(db, sid):
        calls["n"] += 1
        return True

    monkeypatch.setattr("app.stream.session_authorizes", _tracked)

    def _db():
        yield db_session

    gw.app.dependency_overrides[gw.get_db] = _db
    try:
        c = TestClient(gw.app)
        mid = uuid.uuid4()
        r = c.get(
            f"/stream/direct/{mid}",
            params={"uid": str(uuid.uuid4()), "exp": 9999999999,
                    "sig": "deadbeef", "t": 0, "sid": str(uuid.uuid4())},
        )
        assert r.status_code == 401
        assert calls["n"] == 0
    finally:
        gw.app.dependency_overrides.clear()
