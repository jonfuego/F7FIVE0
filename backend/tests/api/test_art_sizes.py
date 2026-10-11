"""Size copies: 300 and 600 px WebP copies written on save, served with
`?w=`, ETag per size, 304 on a matching If-None-Match, and a rerunnable
backfill for art saved before copies existed."""
from __future__ import annotations

import io
import random
import uuid

import pytest
from PIL import Image

from app.config import settings
from app.models.art import ENTITY_MOVIE, ROLE_POSTER
from app.services import art as art_service


def _noisy_jpeg(w: int = 1000, h: int = 1500) -> bytes:
    rnd = random.Random(7)
    img = Image.frombytes("RGB", (w, h), rnd.randbytes(w * h * 3))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
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


def _owner(db):
    from tests.conftest import make_active_session
    return make_active_session(db)[0]


def _save(db, data, entity_id=None):
    eid = entity_id or uuid.uuid4()
    row = art_service.save_upload_bytes(
        db, entity_kind=ENTITY_MOVIE, entity_id=eid, role=ROLE_POSTER,
        data=data, set_by_user_id=_owner(db).id,
        source_kind="upload",
    )
    db.commit()
    return eid, row


def _url(eid, q=""):
    return f"/api/art/{ENTITY_MOVIE}/{eid}/{ROLE_POSTER}{q}"


def test_save_writes_both_copies(db_session, art_root):
    eid, row = _save(db_session, _noisy_jpeg())
    original = art_service._absolute_path(row.local_path)
    for width in (300, 600):
        copy = art_service.copy_path(original, width)
        assert copy.is_file()
        with Image.open(copy, formats=("WEBP",)) as im:
            assert im.width == width


def test_sized_body_smaller_and_unsupported_w_is_original(client, db_session, art_root):
    data = _noisy_jpeg()
    eid, _ = _save(db_session, data)
    orig = client.get(_url(eid))
    r300 = client.get(_url(eid, "?w=300"))
    r600 = client.get(_url(eid, "?w=600"))
    assert orig.status_code == r300.status_code == r600.status_code == 200
    assert len(r300.content) < len(r600.content) < len(orig.content)
    assert r300.headers["content-type"] == "image/webp"
    assert r300.headers["cache-control"].startswith("private")
    assert client.get(_url(eid, "?w=123")).content == orig.content
    assert client.get(_url(eid, "?w=abc")).status_code in (200, 422)


def test_etag_differs_per_size_and_304(client, db_session, art_root):
    eid, _ = _save(db_session, _noisy_jpeg())
    tags = {}
    for q in ("", "?w=300", "?w=600"):
        r = client.get(_url(eid, q))
        tags[q] = r.headers["etag"]
        again = client.get(_url(eid, q), headers={"If-None-Match": tags[q]})
        assert again.status_code == 304
        assert again.content == b""
        assert again.headers["etag"] == tags[q]
        assert again.headers["cache-control"].startswith("private")
    assert len(set(tags.values())) == 3
    stale = client.get(_url(eid, "?w=300"), headers={"If-None-Match": tags[""]})
    assert stale.status_code == 200


def test_missing_copy_generated_on_demand(client, db_session, art_root):
    eid, row = _save(db_session, _noisy_jpeg())
    original = art_service._absolute_path(row.local_path)
    copy = art_service.copy_path(original, 300)
    copy.unlink()
    r = client.get(_url(eid, "?w=300"))
    assert r.status_code == 200 and copy.is_file()


def test_backfill_twice_creates_nothing_new(db_session, art_root):
    rows = [_save(db_session, _noisy_jpeg(400, 600))[1] for _ in range(3)]
    for row in rows:
        original = art_service._absolute_path(row.local_path)
        for width in (300, 600):
            art_service.copy_path(original, width).unlink()
    assert art_service.backfill_art_copies(db_session, batch_size=2) == 6
    assert art_service.backfill_art_copies(db_session, batch_size=2) == 0


def test_clear_override_removes_copies(db_session, art_root):
    eid, row = _save(db_session, _noisy_jpeg(400, 600))
    original = art_service._absolute_path(row.local_path)
    art_service.clear_override(
        db_session, entity_kind=ENTITY_MOVIE, entity_id=eid, role=ROLE_POSTER,
    )
    assert not any(art_service.copy_path(original, w).exists() for w in (300, 600))
