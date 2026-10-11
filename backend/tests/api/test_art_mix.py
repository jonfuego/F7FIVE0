"""Mix pictures: admin set / clear through the existing art endpoints, with
the mix KEY in the URL; members cannot write; the list endpoint reports which
mixes carry a custom picture."""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException
from PIL import Image

from app.config import settings
from app.services import art as art_service


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 30, 90)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _reader(client, db_session):
    """The read route resolves its user through optional_current_user."""
    from app.api.art import optional_current_user
    from app.main import app
    from tests.conftest import make_active_session
    user = make_active_session(db_session)[0]
    app.dependency_overrides[optional_current_user] = lambda: user
    yield


@pytest.fixture()
def art_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "art_root", tmp_path)
    return tmp_path


def test_mix_ids_are_stable_and_distinct():
    ids = art_service.MIX_IDS
    assert set(ids) == {"recently-added", "most-played", "continue-listening", "random"}
    assert len(set(ids.values())) == 4
    assert art_service.parse_entity_id("mix", "random") == ids["random"]


def test_set_list_serve_and_clear_mix_cover(client, art_root):
    up = client.post(
        "/api/admin/art/mix/most-played/cover",
        files={"file": ("m.png", _png(), "image/png")},
    )
    assert up.status_code == 201, up.text
    assert up.json()["entity_id"] == str(art_service.MIX_IDS["most-played"])

    listing = client.get("/api/art/mixes").json()
    assert listing["random"] is None
    url = listing["most-played"]
    assert url.startswith(f"/api/art/mix/{art_service.MIX_IDS['most-played']}/cover?v=")

    assert client.get(url).status_code == 200
    assert client.get(url + "&w=300").status_code == 200

    assert client.delete("/api/admin/art/mix/most-played/cover").status_code == 204
    assert client.get("/api/art/mixes").json()["most-played"] is None
    assert client.get(url).status_code == 404


def test_unknown_mix_key_rejected(client, art_root):
    r = client.post(
        "/api/admin/art/mix/not-a-mix/cover",
        files={"file": ("m.png", _png(), "image/png")},
    )
    assert r.status_code == 404
    assert client.delete("/api/admin/art/mix/not-a-mix/cover").status_code == 404
    # A well-formed uuid that is not a mix id is rejected too.
    other = "11111111-1111-1111-1111-111111111111"
    assert client.get(f"/api/art/mix/{other}/cover").status_code == 404


def test_member_cannot_set_or_clear(client, art_root):
    from app.api.deps import require_admin
    from app.main import app

    def _deny():
        raise HTTPException(status_code=403, detail="admin_required")

    app.dependency_overrides[require_admin] = _deny
    r = client.post(
        "/api/admin/art/mix/random/cover",
        files={"file": ("m.png", _png(), "image/png")},
    )
    assert r.status_code == 403
    assert client.delete("/api/admin/art/mix/random/cover").status_code == 403
