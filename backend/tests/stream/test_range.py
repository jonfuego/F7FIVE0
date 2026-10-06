"""F7FIVE0-Stream direct-play HTTP Range support.

Native players (react-native-track-player / react-native-video) rely on
byte-range seeking far more strictly than browsers. This drives the real
Stream Gateway direct-play route with a signed URL and asserts a Range request
returns 206 with correct Content-Range, Content-Length, Content-Type and
Accept-Ranges: bytes.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services.security import sign_stream_url_params
from app.stream import app as stream_app, get_db as stream_get_db


FILE_BYTES = bytes(range(256)) * 8  # 2048 deterministic bytes


@pytest.fixture()
def media_file(db_session, tmp_path, monkeypatch):
    # SEC-P0-4: the gateway now fails closed, so the file must live under a
    # configured root for direct play to be allowed.
    from app.config import settings

    monkeypatch.setattr(settings, "stream_allowed_roots", str(tmp_path))
    p = tmp_path / "sample.mp4"
    p.write_bytes(FILE_BYTES)
    mf = MediaFile(
        kind=MediaKind.movie,
        ref_id=uuid.uuid4(),
        path=str(p),
        container="mp4",
        size_bytes=len(FILE_BYTES),
        duration_sec=10,
        scan_state=ScanState.ready,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


@pytest.fixture()
def client(db_session):
    def _override_db():
        yield db_session

    stream_app.dependency_overrides[stream_get_db] = _override_db
    c = TestClient(stream_app)
    try:
        yield c
    finally:
        c.close()
        stream_app.dependency_overrides.clear()


def _signed_url(mf) -> str:
    uid = str(uuid.uuid4())
    params = sign_stream_url_params(uuid.UUID(uid), mf.id)
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/stream/direct/{mf.id}?{q}"


def test_direct_play_range_returns_206(client, media_file):
    url = _signed_url(media_file)
    resp = client.get(url, headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == f"bytes 0-99/{len(FILE_BYTES)}"
    assert resp.headers["Content-Length"] == "100"
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.headers["Content-Type"] == "video/mp4"
    assert resp.content == FILE_BYTES[0:100]


def test_direct_play_mid_range(client, media_file):
    url = _signed_url(media_file)
    resp = client.get(url, headers={"Range": "bytes=100-199"})
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == f"bytes 100-199/{len(FILE_BYTES)}"
    assert resp.content == FILE_BYTES[100:200]


def test_direct_play_full_request_advertises_ranges(client, media_file):
    url = _signed_url(media_file)
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.headers["Content-Length"] == str(len(FILE_BYTES))


def test_direct_play_bad_signature_rejected(client, media_file):
    resp = client.get(
        f"/stream/direct/{media_file.id}?uid={uuid.uuid4()}&exp=9999999999&sig=deadbeef&t=0",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 401
