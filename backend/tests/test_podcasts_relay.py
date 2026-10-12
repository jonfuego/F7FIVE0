"""/stream/podcast/{episode_id}: signed URLs, a server file under the stream
roots, and the relay of the publisher's enclosure (Range passed through,
nothing written to disk, guarded on every hop)."""
from __future__ import annotations

import os
import uuid
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services import library_folders
from app.services.security import sign_media_url_params
from app.stream import app as stream_app
from app.stream import get_db as stream_get_db
from tests.conftest import make_active_session
from tests.podcast_helpers import (
    Api, install_dns, install_transport, make_episode, make_podcast, make_user,
)

AUDIO = bytes(range(256)) * 8  # 2048 bytes


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    install_dns(monkeypatch)
    for k in ("library_root_movies", "library_root_tv", "library_root_music",
              "library_root_music_videos", "stream_allowed_roots"):
        monkeypatch.setattr(settings, k, "")
    monkeypatch.setattr(settings, "stream_unsafe_allow_any_path", False)
    monkeypatch.setattr(settings, "path_rewrite_rules", "")


@pytest.fixture()
def stream_client(db_session):
    def _override_db():
        yield db_session

    stream_app.dependency_overrides[stream_get_db] = _override_db
    c = TestClient(stream_app)
    try:
        yield c
    finally:
        c.close()
        stream_app.dependency_overrides.clear()


def _url(episode_id, sess, *, action: str = "podcast", extra: str = "") -> str:
    params = sign_media_url_params(episode_id, action, extra, sess.user_id, sess.id)
    return f"/stream/podcast/{episode_id}?{urlencode(params)}"


def _enclosure_server(request: httpx.Request) -> httpx.Response:
    rng = request.headers.get("range")
    if rng:
        start, _, end = rng.removeprefix("bytes=").partition("-")
        start, end = int(start or 0), int(end) if end else len(AUDIO) - 1
        chunk = AUDIO[start:end + 1]
        return httpx.Response(206, content=chunk, headers={
            "content-type": "audio/mpeg", "content-range": f"bytes {start}-{start + len(chunk) - 1}/{len(AUDIO)}",
            "accept-ranges": "bytes",
        })
    return httpx.Response(200, content=AUDIO, headers={"content-type": "audio/mpeg", "accept-ranges": "bytes"})


# ---------------------------------------------------------------------------
# Signed URLs
# ---------------------------------------------------------------------------
def test_unsigned_and_tampered_urls_are_refused(stream_client, db_session, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session)
    assert stream_client.get(f"/stream/podcast/{ep.id}").status_code == 422
    good = _url(ep.id, sess)
    assert stream_client.get(good.replace("sig=", "sig=0")).status_code == 401
    # A signature for another action or another episode does not work.
    assert stream_client.get(_url(ep.id, sess, action="download")).status_code == 401
    other = make_episode(db_session, make_podcast(db_session, feed_url="https://o.example/f"))
    assert stream_client.get(f"/stream/podcast/{other.id}?" + good.split("?", 1)[1]).status_code == 401
    assert len(calls) == 0


def test_a_revoked_session_does_not_authorise_the_url(stream_client, db_session, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session, revoked=True)
    assert stream_client.get(_url(ep.id, sess)).status_code == 403
    assert len(calls) == 0


def test_a_rotated_session_still_authorises_the_url(stream_client, db_session, monkeypatch):
    install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session, rotated=True)
    assert stream_client.get(_url(ep.id, sess)).status_code == 200


def test_the_route_takes_only_an_episode_id(stream_client, db_session, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session), enclosure_url="https://cdn.show.example/real.mp3")
    _, sess = make_active_session(db_session)
    assert stream_client.get("/stream/podcast/not-a-uuid?uid=1&exp=1&sig=x&sid=x").status_code == 422
    r = stream_client.get(_url(ep.id, sess) + "&url=http%3A%2F%2F127.0.0.1%2Fsecret.mp3&enclosure_url=http%3A%2F%2F10.0.0.1%2Fx")
    assert r.status_code == 200
    assert calls.urls() == ["https://cdn.show.example/real.mp3"]
    assert stream_client.get(_url(uuid.uuid4(), sess)).status_code == 404


# ---------------------------------------------------------------------------
# The relay
# ---------------------------------------------------------------------------
def test_relay_passes_range_through_and_answers_206(stream_client, db_session, monkeypatch, tmp_path):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session)
    before = sorted(os.listdir(tmp_path))
    r = stream_client.get(_url(ep.id, sess), headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-1023/{len(AUDIO)}"
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == AUDIO[:1024]
    assert calls.requests[0].headers["range"] == "bytes=0-1023"
    assert sorted(os.listdir(tmp_path)) == before, "the relay writes nothing to disk"


def test_relay_without_a_range_streams_the_whole_episode(stream_client, db_session, monkeypatch):
    install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess))
    assert r.status_code == 200 and r.content == AUDIO
    assert r.headers.get("accept-ranges") == "bytes"


def test_relay_ignores_a_malformed_range(stream_client, db_session, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess), headers={"Range": "bytes=0-5,10-20"})
    assert r.status_code == 200
    assert "range" not in calls.requests[0].headers


@pytest.mark.parametrize("content_type, url, ok", [
    ("audio/mpeg", "https://cdn.example/a.mp3", True),
    ("audio/x-m4a", "https://cdn.example/a", True),
    ("application/octet-stream", "https://cdn.example/a.mp3", True),
    ("application/octet-stream", "https://cdn.example/a.m4a?token=1", True),
    ("application/octet-stream", "https://cdn.example/a.exe", False),
    ("application/octet-stream", "https://cdn.example/a", False),
    ("text/html", "https://cdn.example/a.mp3", False),
    ("video/mp4", "https://cdn.example/a.mp4", False),
    ("application/json", "https://cdn.example/a.mp3", False),
])
def test_relay_only_passes_audio(stream_client, db_session, monkeypatch, content_type, url, ok):
    install_transport(monkeypatch, lambda r: httpx.Response(200, content=b"zzzz", headers={"content-type": content_type}))
    ep = make_episode(db_session, make_podcast(db_session), enclosure_url=url)
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess))
    assert r.status_code == (200 if ok else 415)


def test_relay_to_a_private_enclosure_is_refused_before_any_request(stream_client, db_session, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = make_episode(db_session, make_podcast(db_session), enclosure_url="http://127.0.0.1/ep.mp3")
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess))
    assert r.status_code in (400, 403)
    assert len(calls) == 0


def test_relay_checks_every_redirect_hop(stream_client, db_session, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.show.example":
            return httpx.Response(302, headers={"location": "http://internal.example/ep.mp3"})
        return httpx.Response(200, content=AUDIO, headers={"content-type": "audio/mpeg"})

    calls = install_transport(monkeypatch, handler)
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess))
    assert r.status_code in (400, 403)
    assert calls.urls() == ["https://cdn.show.example/ep.mp3"]


def test_relay_reports_an_upstream_failure_as_502(stream_client, db_session, monkeypatch):
    install_transport(monkeypatch, lambda r: httpx.Response(404))
    ep = make_episode(db_session, make_podcast(db_session))
    _, sess = make_active_session(db_session)
    assert stream_client.get(_url(ep.id, sess)).status_code == 502


def test_an_episode_with_nothing_to_play_is_a_404(stream_client, db_session):
    ep = make_episode(db_session, make_podcast(db_session, feed_url=None, source="local"), enclosure_url=None)
    _, sess = make_active_session(db_session)
    assert stream_client.get(_url(ep.id, sess)).status_code == 404


# ---------------------------------------------------------------------------
# A file on the server: under the stream roots, with Range
# ---------------------------------------------------------------------------
def _with_file(db_session, tmp_path, *, in_library: bool):
    root = tmp_path / "podcasts"
    (root / "Show").mkdir(parents=True)
    f = root / "Show" / "ep.mp3"
    f.write_bytes(AUDIO)
    if in_library:
        library_folders.save(db_session, {"podcasts": [str(root)]})
    ep = make_episode(db_session, make_podcast(db_session), enclosure_url="https://cdn.show.example/should-not-be-used.mp3")
    mf = MediaFile(kind=MediaKind.podcast_episode, ref_id=ep.id, path=str(f), container="mp3",
                   size_bytes=len(AUDIO), duration_sec=10, scan_state=ScanState.ready)
    db_session.add(mf)
    db_session.flush()
    ep.media_file_id = mf.id
    db_session.commit()
    return ep


def test_a_server_file_under_the_podcasts_root_is_served_with_range(stream_client, db_session, tmp_path, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = _with_file(db_session, tmp_path, in_library=True)
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess), headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == AUDIO[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(AUDIO)}"
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert len(calls) == 0, "a file on the server is never relayed from the publisher"
    assert stream_client.get(_url(ep.id, sess)).status_code == 200


def test_a_path_outside_the_stream_roots_is_rejected(stream_client, db_session, tmp_path, monkeypatch):
    install_transport(monkeypatch, _enclosure_server)
    ep = _with_file(db_session, tmp_path, in_library=False)
    _, sess = make_active_session(db_session)
    assert stream_client.get(_url(ep.id, sess)).status_code == 403


def test_a_missing_server_file_falls_back_to_the_relay(stream_client, db_session, tmp_path, monkeypatch):
    calls = install_transport(monkeypatch, _enclosure_server)
    ep = _with_file(db_session, tmp_path, in_library=True)
    mf = db_session.get(MediaFile, ep.media_file_id)
    mf.scan_state = ScanState.missing
    db_session.commit()
    _, sess = make_active_session(db_session)
    r = stream_client.get(_url(ep.id, sess))
    assert r.status_code == 200 and len(calls) == 1


def test_the_csp_is_unchanged():
    from pathlib import Path
    ts = (Path(__file__).resolve().parents[2] / "frontend" / "lib" / "security-headers.ts").read_text(encoding="utf-8")
    assert '"media-src \'self\' blob:"' in ts


# ---------------------------------------------------------------------------
# Minting the signed URL (API) and playing it (gateway)
# ---------------------------------------------------------------------------
@pytest.fixture()
def api(db_session):
    a = Api(db_session)
    yield a
    a.close()


def _path_and_query(url: str) -> str:
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


def test_the_minted_url_plays_through_the_gateway(api, stream_client, db_session, monkeypatch):
    install_transport(monkeypatch, _enclosure_server)
    user = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    r = api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/stream")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "publisher" and body["position_sec"] == 0
    assert "/stream/podcast/" in body["url"] and "sig=" in body["url"] and "sid=" in body["url"]
    played = stream_client.get(_path_and_query(body["url"]), headers={"Range": "bytes=0-9"})
    assert played.status_code == 206 and played.content == AUDIO[:10]


def test_the_minted_url_resumes_where_the_caller_left_off(api, db_session):
    user = make_user(db_session)
    other = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session))
    api.as_user(user).put(f"/api/podcasts/episodes/{ep.id}/progress", json={"position_sec": 321, "duration_sec": 3600})
    assert api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/stream").json()["position_sec"] == 321
    assert api.as_user(other).post(f"/api/podcasts/episodes/{ep.id}/stream").json()["position_sec"] == 0
    api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/played")
    assert api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/stream").json()["position_sec"] == 0


def test_a_video_episode_is_listed_but_not_played(api, db_session):
    user = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session), enclosure_url="https://cdn.show.example/v.mp4")
    ep.enclosure_type = "video/mp4"
    db_session.flush()
    r = api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/stream")
    assert r.status_code == 422 and r.json()["detail"] == "video_not_supported"
    listed = api.as_user(user).get(f"/api/podcasts/{ep.podcast_id}").json()["episodes"]
    assert listed[0]["is_video"] is True


def test_an_episode_with_no_file_and_no_enclosure_has_nothing_to_play(api, db_session):
    user = make_user(db_session)
    ep = make_episode(db_session, make_podcast(db_session, feed_url=None, source="local"), enclosure_url=None)
    assert api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/stream").status_code == 404


def test_a_server_file_is_reported_as_the_source(api, db_session, tmp_path):
    user = make_user(db_session)
    ep = _with_file(db_session, tmp_path, in_library=True)
    body = api.as_user(user).post(f"/api/podcasts/episodes/{ep.id}/stream").json()
    assert body["source"] == "server_file" and body["container"] == "mp3"

