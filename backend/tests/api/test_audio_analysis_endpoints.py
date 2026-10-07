"""API tests for the Phase 2 track + media-file endpoints.

Covers loudness / waveform / lyrics / similar / track-radio / streams /
subtitle-vtt (signed + bearer + bad sig) / stream-start new fields / download
signing + 409 paths. Self-contained: all ffmpeg/ffprobe/service calls are
monkeypatched, so no real media or ffmpeg on PATH is required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.audio_analysis import (
    ANALYSIS_VERSION, TrackAudioAnalysis, TrackSimilarity,
)
from app.models.art import ArtOverride
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, Track
from app.models.user import User
from app.services import security
from tests.conftest import make_active_session


@pytest.fixture()
def authed_client(db_session):
    """TestClient that authenticates the subtitle/download `optional_current_user`
    seam (which is NOT covered by the shared `client` fixture's current_user
    override, since it resolves the bearer only when a header is present)."""
    from fastapi.testclient import TestClient
    from app.api.deps import current_user, get_db, require_admin
    from app.api.media_files import optional_current_user
    from app.main import app

    admin = User(
        id=uuid.uuid4(), username="test-admin", display_name="Test Admin",
        password_hash="x", role="admin", is_active=True,
    )

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[optional_current_user] = lambda: admin
    try:
        c = TestClient(app)
        yield c
        c.close()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fixtures: an artist/album with two tracks, each with a ready media file.
# ---------------------------------------------------------------------------
@pytest.fixture()
def library(db_session, tmp_path):
    artist = Artist(name="Boards of Canada", genres=["electronic", "idm"])
    db_session.add(artist)
    db_session.flush()
    album = Album(
        artist_id=artist.id, title="Music Has the Right",
        genres=["electronic", "idm"],
    )
    db_session.add(album)
    db_session.flush()

    tracks = []
    files = []
    for i in range(2):
        t = Track(album_id=album.id, title=f"Track {i}", track_number=i + 1,
                  duration_sec=200)
        db_session.add(t)
        db_session.flush()
        p = tmp_path / f"track{i}.flac"
        p.write_bytes(b"not real audio")
        mf = MediaFile(
            kind=MediaKind.track, ref_id=t.id, path=str(p),
            container="flac", scan_state=ScanState.ready, duration_sec=200,
        )
        db_session.add(mf)
        db_session.flush()
        tracks.append(t)
        files.append(mf)
    db_session.commit()
    return {"artist": artist, "album": album, "tracks": tracks, "files": files}


# ---------------------------------------------------------------------------
# loudness
# ---------------------------------------------------------------------------
def test_loudness_nulls_when_unanalyzed(client, library):
    t = library["tracks"][0]
    resp = client.get(f"/api/tracks/{t.id}/loudness")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "integrated_lufs": None, "track_gain_db": None, "album_gain_db": None,
    }


def test_loudness_returns_values(client, db_session, library):
    t = library["tracks"][0]
    db_session.add(TrackAudioAnalysis(
        track_id=t.id, integrated_lufs=-14.2, track_gain_db=-1.8,
        album_gain_db=-2.0, analysis_version=ANALYSIS_VERSION,
        analyzed_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    resp = client.get(f"/api/tracks/{t.id}/loudness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["integrated_lufs"] == -14.2
    assert body["track_gain_db"] == -1.8
    assert body["album_gain_db"] == -2.0


def test_loudness_404_unknown_track(client, library):
    resp = client.get(f"/api/tracks/{uuid.uuid4()}/loudness")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# waveform
# ---------------------------------------------------------------------------
def test_waveform_empty_when_unanalyzed(client, library):
    t = library["tracks"][0]
    resp = client.get(f"/api/tracks/{t.id}/waveform")
    assert resp.status_code == 200
    assert resp.json() == {"peaks": [], "version": 0}


def test_waveform_returns_peaks(client, db_session, library):
    t = library["tracks"][0]
    db_session.add(TrackAudioAnalysis(
        track_id=t.id, waveform_peaks=[0, 50, 100, 50, 0],
        analysis_version=ANALYSIS_VERSION,
        analyzed_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    resp = client.get(f"/api/tracks/{t.id}/waveform")
    assert resp.status_code == 200
    body = resp.json()
    assert body["peaks"] == [0, 50, 100, 50, 0]
    assert body["version"] == ANALYSIS_VERSION


# ---------------------------------------------------------------------------
# lyrics
# ---------------------------------------------------------------------------
def test_lyrics_from_lrc_sidecar(client, library, tmp_path):
    t = library["tracks"][0]
    mf = library["files"][0]
    # Write an .lrc next to the file.
    lrc = mf.path.rsplit(".", 1)[0] + ".lrc"
    with open(lrc, "w", encoding="utf-8") as fh:
        fh.write("[00:01.00]hello\n[00:02.00]world\n")
    resp = client.get(f"/api/tracks/{t.id}/lyrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["synced"] is True
    assert body["source"] == "lrc"
    assert body["lines"][0] == {"time_ms": 1000, "text": "hello"}


def test_lyrics_from_embedded(client, library, monkeypatch):
    from app.services import lyrics as lyrics_svc
    t = library["tracks"][1]
    monkeypatch.setattr(
        lyrics_svc, "read_embedded_lyrics",
        lambda p: lyrics_svc.LyricsResult(False, None, "embedded words", "embedded"),
    )
    resp = client.get(f"/api/tracks/{t.id}/lyrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "embedded"
    assert body["text"] == "embedded words"
    assert body["synced"] is False


def test_lyrics_empty(client, library, monkeypatch):
    from app.services import lyrics as lyrics_svc
    t = library["tracks"][1]
    monkeypatch.setattr(lyrics_svc, "read_embedded_lyrics", lambda p: None)
    resp = client.get(f"/api/tracks/{t.id}/lyrics")
    assert resp.status_code == 200
    assert resp.json() == {
        "synced": False, "lines": None, "text": None, "source": None,
    }


# ---------------------------------------------------------------------------
# similar + track-radio
# ---------------------------------------------------------------------------
def test_similar_from_graph(client, db_session, library):
    t0, t1 = library["tracks"]
    db_session.add(TrackSimilarity(
        track_id=t0.id, similar_track_id=t1.id, score=0.9,
    ))
    db_session.commit()
    resp = client.get(f"/api/tracks/{t0.id}/similar")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["track_id"] == str(t1.id)
    assert items[0]["media_file_id"] == str(library["files"][1].id)


def test_similar_falls_back_to_artist(client, library):
    # No similarity edges: same-artist fallback returns the sibling track.
    t0 = library["tracks"][0]
    resp = client.get(f"/api/tracks/{t0.id}/similar")
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {it["track_id"] for it in items}
    assert str(library["tracks"][1].id) in ids
    assert str(t0.id) not in ids  # seed excluded


def test_track_radio_shape(client, db_session, library):
    t0, t1 = library["tracks"]
    db_session.add(TrackSimilarity(track_id=t0.id, similar_track_id=t1.id, score=0.8))
    db_session.commit()
    resp = client.get(f"/api/auto-playlist/track-radio/{t0.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "track-radio"
    assert body["params"]["track_id"] == str(t0.id)
    assert "items" in body and "diagnostic" in body
    # Seed leads the queue.
    assert body["items"][0]["track_id"] == str(t0.id)


# ---------------------------------------------------------------------------
# streams
# ---------------------------------------------------------------------------
def test_streams(client, library, monkeypatch):
    from app.services import media_streams as ms
    mf = library["files"][0]
    fake = {
        "subtitles": [
            {"index": 2, "codec": "subrip", "language": "eng", "title": None,
             "forced": False, "default": True},
        ],
        "audio": [
            {"index": 1, "codec": "flac", "language": "eng", "channels": 2,
             "title": None, "default": True},
        ],
    }
    monkeypatch.setattr(ms, "probe_streams", lambda path: fake)
    resp = client.get(f"/api/media-files/{mf.id}/streams")
    assert resp.status_code == 200
    assert resp.json() == fake


def test_streams_probe_failure_409(client, library, monkeypatch):
    from app.services import media_streams as ms
    mf = library["files"][0]
    monkeypatch.setattr(ms, "probe_streams", lambda path: None)
    resp = client.get(f"/api/media-files/{mf.id}/streams")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# subtitle .vtt  (bearer, signed, bad sig, image sub 409)
# ---------------------------------------------------------------------------
_VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n"


def _patch_subs(monkeypatch, codec="subrip", index=2, vtt=_VTT):
    from app.services import media_streams as ms
    monkeypatch.setattr(ms, "probe_streams", lambda path: {
        "subtitles": [{"index": index, "codec": codec, "language": "eng",
                       "title": None, "forced": False, "default": True}],
        "audio": [],
    })
    monkeypatch.setattr(ms, "extract_subtitle_vtt", lambda path, idx, **kw: vtt)


def test_subtitle_vtt_with_bearer(authed_client, library, monkeypatch):
    _patch_subs(monkeypatch)
    mf = library["files"][0]
    resp = authed_client.get(f"/api/media-files/{mf.id}/subtitles/2.vtt")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/vtt")
    assert resp.text == _VTT


def test_subtitle_vtt_signed_no_bearer(db_session, library, monkeypatch):
    """A valid signature serves the vtt with NO bearer header (200 text/vtt)."""
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app
    from app.services import media_streams as ms

    _patch_subs(monkeypatch)
    mf = library["files"][0]

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        c = TestClient(app)
        sess = make_active_session(db_session)[1]
        params = security.sign_media_url_params(mf.id, "subtitle", "2", sess.user_id, sess.id)
        resp = c.get(
            f"/api/media-files/{mf.id}/subtitles/2.vtt",
            params={"uid": params["uid"], "sid": params["sid"],
                    "exp": params["exp"], "sig": params["sig"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/vtt")
        c.close()
    finally:
        app.dependency_overrides.clear()


def test_subtitle_vtt_bad_sig_401(db_session, library, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app

    _patch_subs(monkeypatch)
    mf = library["files"][0]

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        c = TestClient(app)
        resp = c.get(
            f"/api/media-files/{mf.id}/subtitles/2.vtt",
            params={"uid": str(uuid.uuid4()), "exp": 9999999999, "sig": "deadbeef"},
        )
        assert resp.status_code == 401
        c.close()
    finally:
        app.dependency_overrides.clear()


def test_subtitle_vtt_no_auth_401(db_session, library, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app

    _patch_subs(monkeypatch)
    mf = library["files"][0]

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        c = TestClient(app)
        resp = c.get(f"/api/media-files/{mf.id}/subtitles/2.vtt")
        assert resp.status_code == 401
        c.close()
    finally:
        app.dependency_overrides.clear()


def test_subtitle_vtt_image_sub_409(authed_client, library, monkeypatch):
    _patch_subs(monkeypatch, codec="hdmv_pgs_subtitle")
    mf = library["files"][0]
    resp = authed_client.get(f"/api/media-files/{mf.id}/subtitles/2.vtt")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "image_subtitle_burn_required"


# ---------------------------------------------------------------------------
# download signing + 409 paths
# ---------------------------------------------------------------------------
@pytest.fixture()
def audio_file(db_session, library):
    """The first track's media file is FLAC (audio, direct-playable)."""
    return library["files"][0]


@pytest.fixture()
def video_file(db_session, tmp_path):
    """A non-direct-play video (mkv / hevc)."""
    p = tmp_path / "movie.mkv"
    p.write_bytes(b"video bytes here")
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
        container="mkv", video_codec="hevc", audio_codec="eac3",
        scan_state=ScanState.ready, duration_sec=100,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


def test_download_audio_original_with_bearer(authed_client, audio_file):
    resp = authed_client.get(f"/api/media-files/{audio_file.id}/download")
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_download_audio_signed_no_bearer(db_session, audio_file):
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        c = TestClient(app)
        sess = make_active_session(db_session)[1]
        params = security.sign_media_url_params(
            audio_file.id, "download", "original", sess.user_id, sess.id,
        )
        resp = c.get(
            f"/api/media-files/{audio_file.id}/download",
            params={"quality": "original", "uid": params["uid"], "sid": params["sid"],
                    "exp": params["exp"], "sig": params["sig"]},
        )
        assert resp.status_code == 200, resp.text
        c.close()
    finally:
        app.dependency_overrides.clear()


def test_download_bad_sig_401(db_session, audio_file):
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        c = TestClient(app)
        resp = c.get(
            f"/api/media-files/{audio_file.id}/download",
            params={"quality": "original", "uid": str(uuid.uuid4()),
                    "exp": 9999999999, "sig": "deadbeef"},
        )
        assert resp.status_code == 401
        c.close()
    finally:
        app.dependency_overrides.clear()


def test_download_invalid_quality_422(authed_client, audio_file):
    resp = authed_client.get(
        f"/api/media-files/{audio_file.id}/download", params={"quality": "4k"},
    )
    assert resp.status_code == 422


def test_download_video_not_available_offline_409(authed_client, video_file):
    # Non-direct-play video with the transcode flag off -> documented 409.
    resp = authed_client.get(
        f"/api/media-files/{video_file.id}/download", params={"quality": "720p"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "not_available_offline"


# ---------------------------------------------------------------------------
# stream/start new fields echoed
# ---------------------------------------------------------------------------
def test_stream_start_echoes_new_fields(client, audio_file):
    resp = client.post("/api/stream/start", json={
        "file_id": str(audio_file.id),
        "audio_track_index": 1,
        "subtitle": 2,
        "quality": "720p",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["audio_track_index"] == 1
    assert body["subtitle"] == 2
    assert body["quality"] == "720p"


def test_stream_start_subtitle_off(client, audio_file):
    resp = client.post("/api/stream/start", json={
        "file_id": str(audio_file.id),
        "subtitle": "off",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["subtitle"] == "off"


def test_stream_start_defaults_preserved(client, audio_file):
    # Omitting the new fields keeps the old behavior; quality defaults original.
    resp = client.post("/api/stream/start", json={"file_id": str(audio_file.id)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["audio_track_index"] is None
    assert body["subtitle"] is None
    assert body["quality"] == "original"


def test_stream_start_bad_subtitle_422(client, audio_file):
    resp = client.post("/api/stream/start", json={
        "file_id": str(audio_file.id),
        "subtitle": "nonsense",
    })
    assert resp.status_code == 422


def test_stream_start_cover_path_is_resolved_art_url(client, db_session, library, audio_file):
    """Regression: the audio stream/start cover_path must be the client-ready
    `/api/art/...` URL (what resolve_art/the album detail hand out), never the
    raw `albums.cover_path` DB column, which is a scanner/Lidarr path the
    browser cannot load. A client that copies this into a dock queue item (the
    web watch route) would otherwise render a broken image. See batch4/02-art."""
    from app.models.art import ENTITY_ALBUM, ROLE_COVER
    from app.services.art import SYSTEM_USER_ID

    db_session.add(User(
        id=SYSTEM_USER_ID, username="system", display_name="System",
        password_hash="!", role="admin", is_active=False,
    ))
    db_session.flush()

    album = library["album"]
    # Simulate a real library where the raw DB column holds a non-servable path.
    raw_scanner_path = "/mnt/library/music/Godflesh/Decay/cover.jpg"
    album.cover_path = raw_scanner_path
    db_session.add(ArtOverride(
        entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER,
        local_path="cover.jpg", source_kind="local", set_by=SYSTEM_USER_ID,
    ))
    db_session.commit()

    resp = client.post("/api/stream/start", json={"file_id": str(audio_file.id)})
    assert resp.status_code == 200, resp.text
    cover = resp.json()["cover_path"]
    assert cover is not None
    assert cover != raw_scanner_path
    assert cover.startswith(f"/api/art/{ENTITY_ALBUM}/{album.id}/{ROLE_COVER}")
