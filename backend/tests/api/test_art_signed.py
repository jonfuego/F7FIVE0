"""Signed art URL support on the /api/art read endpoint.

Android's media-notification artwork loader can't attach a bearer header, so
the read endpoint also accepts a short-lived HMAC-signed query (uid/exp/sig)
bound to the exact art path. These tests cover:

- signed URL with no bearer -> 200 + image content type
- tampered signature -> 401
- expired signature -> 401
- bearer auth with no signature -> still 200 (unchanged)
- the sign/verify helper round-trips and rejects tamper + expiry

The endpoint needs a real override file on disk to return 200. Rather than
depend on real media or the M: art root, we point settings.art_root at a temp
dir and write a tiny in-memory PNG through the same service the write path uses,
so the tests are self-contained.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.art import optional_current_user
from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.models.art import ENTITY_MOVIE, ROLE_POSTER
from app.models.user import User
from app.services import art as art_service
from app.services import security as security_service
from app.services.security import (
    build_signed_art_url,
    sign_art_url_params,
    verify_art_url_params,
)


_PNG_1x1 = None


def _png_bytes() -> bytes:
    """A minimal valid 1x1 PNG, encoded once."""
    global _PNG_1x1
    if _PNG_1x1 is None:
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), (10, 20, 30)).save(buf, format="PNG")
        _PNG_1x1 = buf.getvalue()
    return _PNG_1x1


@pytest.fixture()
def art_root(tmp_path, monkeypatch):
    """Point the art root at a temp dir for the duration of a test."""
    monkeypatch.setattr(settings, "art_root", tmp_path)
    return tmp_path


@pytest.fixture()
def owner(db_session):
    u = User(
        username="art-user", display_name="Art User",
        password_hash="x", role="member", is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def override_row(db_session, owner, art_root):
    """Create a real movie/poster override with a file on disk."""
    entity_id = uuid.uuid4()
    art_service.save_upload_bytes(
        db_session,
        entity_kind=ENTITY_MOVIE,
        entity_id=entity_id,
        role=ROLE_POSTER,
        data=_png_bytes(),
        set_by_user_id=owner.id,
        source_kind="upload",
        source_ref="test.png",
    )
    db_session.commit()
    return entity_id


@pytest.fixture()
def anon_client(db_session):
    """A TestClient with the DB overridden but NO auth override.

    Unauthenticated requests must be rejected unless a valid signature is
    present, so we deliberately do not override current_user here.
    """
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()
        app.dependency_overrides.clear()


def _art_path(entity_id: uuid.UUID) -> str:
    return f"/api/art/{ENTITY_MOVIE}/{entity_id}/{ROLE_POSTER}"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------
def test_signed_url_without_bearer_returns_200_and_image(
    anon_client, override_row, owner,
):
    params = sign_art_url_params(
        ENTITY_MOVIE, override_row, ROLE_POSTER, owner.id,
    )
    resp = anon_client.get(_art_path(override_row), params=params)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/")


def test_tampered_signature_returns_401(anon_client, override_row, owner):
    params = sign_art_url_params(
        ENTITY_MOVIE, override_row, ROLE_POSTER, owner.id,
    )
    params["sig"] = params["sig"][:-1] + ("0" if params["sig"][-1] != "0" else "1")
    resp = anon_client.get(_art_path(override_row), params=params)
    assert resp.status_code == 401, resp.text


def test_signature_for_a_different_image_is_rejected(
    anon_client, override_row, owner,
):
    # Mint a valid signature for a DIFFERENT entity id, then try to use it on
    # the real one. The path binding must reject it.
    other_id = uuid.uuid4()
    params = sign_art_url_params(
        ENTITY_MOVIE, other_id, ROLE_POSTER, owner.id,
    )
    resp = anon_client.get(_art_path(override_row), params=params)
    assert resp.status_code == 401, resp.text


def test_expired_signature_returns_401(anon_client, override_row, owner):
    # Build a signature whose exp is already in the past by signing over the
    # same payload the helper uses with a negative TTL.
    params = sign_art_url_params(
        ENTITY_MOVIE, override_row, ROLE_POSTER, owner.id, ttl_hours=-1,
    )
    resp = anon_client.get(_art_path(override_row), params=params)
    assert resp.status_code == 401, resp.text


def test_no_bearer_and_no_signature_is_401(anon_client, override_row):
    resp = anon_client.get(_art_path(override_row))
    assert resp.status_code == 401, resp.text


def test_bearer_auth_still_works_without_signature(
    db_session, override_row, owner, art_root,
):
    # Override current_user (as the real bearer dependency would resolve) and
    # confirm a plain, unsigned request still serves the image.
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[optional_current_user] = lambda: owner
    try:
        c = TestClient(app)
        resp = c.get(_art_path(override_row))
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("image/")
        c.close()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper round-trip tests
# ---------------------------------------------------------------------------
def test_sign_verify_round_trip():
    entity_id = uuid.uuid4()
    user_id = uuid.uuid4()
    params = sign_art_url_params(ENTITY_MOVIE, entity_id, ROLE_POSTER, user_id)
    assert set(params) == {"uid", "exp", "sig"}
    assert verify_art_url_params(
        ENTITY_MOVIE, entity_id, ROLE_POSTER,
        params["uid"], params["exp"], params["sig"],
    )


def test_verify_rejects_tampered_sig():
    entity_id = uuid.uuid4()
    user_id = uuid.uuid4()
    params = sign_art_url_params(ENTITY_MOVIE, entity_id, ROLE_POSTER, user_id)
    bad = params["sig"][:-1] + ("0" if params["sig"][-1] != "0" else "1")
    assert not verify_art_url_params(
        ENTITY_MOVIE, entity_id, ROLE_POSTER,
        params["uid"], params["exp"], bad,
    )


def test_verify_rejects_different_path():
    entity_id = uuid.uuid4()
    user_id = uuid.uuid4()
    params = sign_art_url_params(ENTITY_MOVIE, entity_id, ROLE_POSTER, user_id)
    # Same sig, different role -> reject.
    assert not verify_art_url_params(
        ENTITY_MOVIE, entity_id, "backdrop",
        params["uid"], params["exp"], params["sig"],
    )


def test_verify_rejects_expired():
    entity_id = uuid.uuid4()
    user_id = uuid.uuid4()
    params = sign_art_url_params(
        ENTITY_MOVIE, entity_id, ROLE_POSTER, user_id, ttl_hours=-1,
    )
    assert params["exp"] < int(datetime.now(timezone.utc).timestamp())
    assert not verify_art_url_params(
        ENTITY_MOVIE, entity_id, ROLE_POSTER,
        params["uid"], params["exp"], params["sig"],
    )


def test_build_signed_art_url_format():
    entity_id = uuid.uuid4()
    user_id = uuid.uuid4()
    url = build_signed_art_url(
        "https://media.example.com/", ENTITY_MOVIE, entity_id, ROLE_POSTER,
        user_id,
    )
    prefix = f"https://media.example.com/api/art/{ENTITY_MOVIE}/{entity_id}/{ROLE_POSTER}?"
    assert url.startswith(prefix)
    assert "uid=" in url and "exp=" in url and "sig=" in url
