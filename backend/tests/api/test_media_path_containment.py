"""Media paths outside the library folders are refused on every API route.

The stream gateway has always held a file to the library roots. These cover the
same rule for the API side (`services/media_paths.py`): download, streams,
subtitle, stream start, lyrics, audio analysis and the *arr sync. A row whose
path points elsewhere must answer 403 `path_outside_library_roots` and must
never reach ffprobe, ffmpeg or a file read.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, Track
from app.models.user import User


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    """A library root with one file inside it and one file outside it."""
    from app.config import settings

    lib = tmp_path / "library"
    out = tmp_path / "elsewhere"
    lib.mkdir()
    out.mkdir()
    monkeypatch.setattr(settings, "stream_allowed_roots", str(lib))
    monkeypatch.setattr(settings, "stream_unsafe_allow_any_path", False)
    for key in ("library_root_movies", "library_root_tv", "library_root_music",
                "library_root_music_videos"):
        monkeypatch.setattr(settings, key, "")
    return lib, out


@pytest.fixture()
def authed_client(db_session):
    from fastapi.testclient import TestClient
    from app.api.deps import current_session_id, current_user, get_db, require_admin
    from app.api.media_files import optional_current_user
    from app.main import app
    from tests.conftest import make_active_session

    admin = User(
        id=uuid.uuid4(), username="test-admin", display_name="Test Admin",
        password_hash="x", role="admin", is_active=True,
    )
    db_session.add(admin)
    db_session.flush()
    sess = make_active_session(db_session, user=admin)[1]

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[optional_current_user] = lambda: admin
    app.dependency_overrides[current_session_id] = lambda: sess.id
    try:
        c = TestClient(app)
        yield c
        c.close()
    finally:
        app.dependency_overrides.clear()


def _track_file(db, path: Path, *, state=ScanState.ready) -> tuple[Track, MediaFile]:
    artist = Artist(name=f"A {uuid.uuid4().hex[:6]}")
    db.add(artist)
    db.flush()
    album = Album(artist_id=artist.id, title="Album")
    db.add(album)
    db.flush()
    t = Track(album_id=album.id, title="T", track_number=1, duration_sec=60)
    db.add(t)
    db.flush()
    mf = MediaFile(
        kind=MediaKind.track, ref_id=t.id, path=str(path), container="flac",
        scan_state=state, duration_sec=60, size_bytes=14,
    )
    db.add(mf)
    db.commit()
    return t, mf


def _movie_file(db, path: Path) -> MediaFile:
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(path),
        container="mkv", video_codec="hevc", audio_codec="eac3",
        scan_state=ScanState.ready, duration_sec=100, size_bytes=14,
    )
    db.add(mf)
    db.commit()
    return mf


@pytest.fixture()
def no_tools(monkeypatch):
    """Fail the test if anything probes, extracts or reads lyrics."""
    from app.services import audio_analysis, lyrics, media_streams

    def _boom(*a, **kw):
        raise AssertionError("an outside-root path reached a probe/extract/read")

    for mod, name in ((media_streams, "probe_streams"),
                      (media_streams, "extract_subtitle_vtt"),
                      (lyrics, "resolve_lyrics"),
                      (audio_analysis, "measure_loudness"),
                      (audio_analysis, "compute_waveform")):
        monkeypatch.setattr(mod, name, _boom)


# ---------------------------------------------------------------------------
# Routes: outside the roots -> 403 path_outside_library_roots
# ---------------------------------------------------------------------------
def test_download_outside_root_403(authed_client, db_session, roots, no_tools):
    _lib, out = roots
    secret = out / "secret.flac"
    secret.write_bytes(b"top secret bytes")
    _t, mf = _track_file(db_session, secret)
    resp = authed_client.get(f"/api/media-files/{mf.id}/download")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "path_outside_library_roots"
    assert b"top secret" not in resp.content


def test_download_inside_root_still_works(authed_client, db_session, roots, no_tools):
    lib, _out = roots
    f = lib / "a.flac"
    f.write_bytes(b"inside bytes")
    _t, mf = _track_file(db_session, f)
    resp = authed_client.get(f"/api/media-files/{mf.id}/download")
    assert resp.status_code == 200
    assert resp.content == b"inside bytes"


def test_streams_outside_root_403(authed_client, db_session, roots, no_tools):
    _lib, out = roots
    f = out / "v.mkv"
    f.write_bytes(b"x")
    mf = _movie_file(db_session, f)
    resp = authed_client.get(f"/api/media-files/{mf.id}/streams")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "path_outside_library_roots"


def test_subtitle_outside_root_403(authed_client, db_session, roots, no_tools):
    _lib, out = roots
    f = out / "v.mkv"
    f.write_bytes(b"x")
    mf = _movie_file(db_session, f)
    resp = authed_client.get(f"/api/media-files/{mf.id}/subtitles/2.vtt")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "path_outside_library_roots"


def test_stream_start_outside_root_403(authed_client, db_session, roots, no_tools):
    _lib, out = roots
    f = out / "v.mkv"
    f.write_bytes(b"x")
    mf = _movie_file(db_session, f)
    # Plain start and a start that asks for an audio track (which probes).
    for body in ({"file_id": str(mf.id)},
                 {"file_id": str(mf.id), "audio_track_index": 1}):
        resp = authed_client.post("/api/stream/start", json=body)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "path_outside_library_roots"


def test_stream_start_inside_root_ok(authed_client, db_session, roots):
    lib, _out = roots
    f = lib / "v.mp4"
    f.write_bytes(b"x")
    mf = _movie_file(db_session, f)
    mf.container, mf.video_codec, mf.audio_codec = "mp4", "h264", "aac"
    db_session.commit()
    resp = authed_client.post("/api/stream/start", json={"file_id": str(mf.id)})
    assert resp.status_code == 200, resp.text


def test_lyrics_outside_root_403_and_sidecar_unread(
    authed_client, db_session, roots, no_tools,
):
    _lib, out = roots
    f = out / "song.flac"
    f.write_bytes(b"x")
    (out / "song.lrc").write_text("[00:01.00]secret words\n", encoding="utf-8")
    t, _mf = _track_file(db_session, f)
    resp = authed_client.get(f"/api/tracks/{t.id}/lyrics")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "path_outside_library_roots"
    assert "secret words" not in resp.text


def test_lyrics_inside_root_reads_sidecar(authed_client, db_session, roots):
    lib, _out = roots
    f = lib / "song.flac"
    f.write_bytes(b"x")
    (lib / "song.lrc").write_text("[00:01.00]hello\n", encoding="utf-8")
    t, _mf = _track_file(db_session, f)
    resp = authed_client.get(f"/api/tracks/{t.id}/lyrics")
    assert resp.status_code == 200
    assert resp.json()["lines"][0]["text"] == "hello"


# ---------------------------------------------------------------------------
# Audio analysis
# ---------------------------------------------------------------------------
def test_audio_analysis_skips_outside_root(db_session, roots, no_tools):
    from app.services import audio_analysis

    _lib, out = roots
    f = out / "song.flac"
    f.write_bytes(b"x")
    t, _mf = _track_file(db_session, f)
    # no_tools makes measure_loudness/compute_waveform raise if they are reached.
    assert audio_analysis.analyze_track(db_session, t.id) == audio_analysis.STATUS_NO_FILE


def test_audio_analysis_runs_inside_root(db_session, roots, monkeypatch):
    from app.services import audio_analysis

    lib, _out = roots
    f = lib / "song.flac"
    f.write_bytes(b"x")
    t, _mf = _track_file(db_session, f)
    seen: list[str] = []
    monkeypatch.setattr(audio_analysis, "measure_loudness",
                        lambda p, **kw: seen.append(p) or -14.0)
    monkeypatch.setattr(audio_analysis, "compute_waveform", lambda p, **kw: [0.1, 0.2])
    assert audio_analysis.analyze_track(db_session, t.id) == audio_analysis.STATUS_ANALYZED
    assert seen == [str(f.resolve())]


# ---------------------------------------------------------------------------
# Translated and linked paths
# ---------------------------------------------------------------------------
def test_translated_path_inside_roots_is_allowed(db_session, roots, monkeypatch):
    """A legacy row still stored as a mapped drive letter (`Z:/a.flac`) resolves
    through path_map to the real folder and is accepted."""
    from app.services import media_paths

    lib, _out = roots
    real = lib / "a.flac"
    real.write_bytes(b"x")
    monkeypatch.setattr(
        media_paths, "translate_path",
        lambda p: str(lib) + p[2:] if p and p[:2].lower() == "z:" else p,
    )
    _t, mf = _track_file(db_session, Path("Z:/a.flac"))
    assert media_paths.resolve_contained_media_path(db_session, mf) == real.resolve()


def test_translated_path_that_lands_outside_is_refused(db_session, roots, monkeypatch):
    from fastapi import HTTPException
    from app.services import media_paths

    _lib, out = roots
    monkeypatch.setattr(
        media_paths, "translate_path",
        lambda p: str(out) + p[2:] if p and p[:2].lower() == "z:" else p,
    )
    with pytest.raises(HTTPException) as ei:
        media_paths.resolve_contained_media_path(db_session, "Z:/a.flac")
    assert ei.value.status_code == 403
    assert ei.value.detail == "path_outside_library_roots"


def test_symlink_inside_root_pointing_outside_is_refused(
    authed_client, db_session, roots, no_tools,
):
    lib, out = roots
    target = out / "secret.flac"
    target.write_bytes(b"top secret bytes")
    link = lib / "link.flac"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink on this OS/privilege level: {exc}")
    _t, mf = _track_file(db_session, link)
    resp = authed_client.get(f"/api/media-files/{mf.id}/download")
    assert resp.status_code == 403
    assert b"top secret" not in resp.content


def test_no_roots_configured_refuses_everything(db_session, roots, monkeypatch):
    from fastapi import HTTPException
    from app.config import settings
    from app.services import media_paths

    lib, _out = roots
    f = lib / "a.flac"
    f.write_bytes(b"x")
    monkeypatch.setattr(settings, "stream_allowed_roots", "")
    with pytest.raises(HTTPException):
        media_paths.resolve_contained_media_path(db_session, f)


def test_unsafe_dev_flag_still_bypasses(db_session, roots, monkeypatch):
    from app.config import settings
    from app.services import media_paths

    _lib, out = roots
    f = out / "a.flac"
    f.write_bytes(b"x")
    monkeypatch.setattr(settings, "stream_unsafe_allow_any_path", True)
    assert media_paths.resolve_contained_media_path(db_session, f) == f.resolve()


# ---------------------------------------------------------------------------
# *arr sync: a hostile path is never probed or stored as ready
# ---------------------------------------------------------------------------
def test_arr_path_outside_roots_is_never_probed(db_session, roots, monkeypatch):
    from app.services import sync

    _lib, out = roots
    probed: list[str] = []
    monkeypatch.setattr(sync.ffprobe, "probe", lambda p, *a, **kw: probed.append(p))
    stats = sync.SyncStats()
    mf = sync._upsert_media_file(
        db_session, kind=MediaKind.movie, ref_id=uuid.uuid4(),
        path=str(out / "evil.mkv"), arr_file={"size": 1}, stats=stats,
    )
    db_session.commit()
    assert mf is None
    assert probed == []
    assert stats.files_refused == 1
    assert stats.files_upserted == 0
    assert db_session.query(MediaFile).count() == 0


def test_arr_path_inside_roots_is_probed(db_session, roots, monkeypatch):
    from app.services import sync

    lib, _out = roots
    good = lib / "good.mkv"
    good.write_bytes(b"x")
    probed: list[str] = []

    # Probe finds nothing usable; the point is only that an inside path reaches it.
    monkeypatch.setattr(sync.ffprobe, "probe", lambda p, *a, **kw: probed.append(p))
    stats = sync.SyncStats()
    mf = sync._upsert_media_file(
        db_session, kind=MediaKind.movie, ref_id=uuid.uuid4(),
        path=str(good), arr_file={"size": 1}, stats=stats,
    )
    assert mf is not None
    assert probed == [str(good)]
    assert stats.files_refused == 0
