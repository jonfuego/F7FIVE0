"""Track selection that actually re-routes the transcode, signed lock-screen
art on stream/start, and the On Deck endpoint (spec sections E, H, I;
criteria 21, 38, 40).

Self-contained: ffprobe is monkeypatched, ffmpeg is never spawned (the
gateway tests stop at the master playlist, which is pure).
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from app.config import settings
from app.models.art import ENTITY_ALBUM, ROLE_COVER
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, Track
from app.models.playback import WatchProgress
from app.models.tv import Episode, Series
from app.services import art as art_service
from app.services import media_streams
from app.services.on_deck import EpisodeRef, ProgressRef, next_episode
from app.services.playback import Variant
from app.services.security import (
    sign_stream_url_params, verify_art_url_params, verify_stream_url_params,
)
from app.services.track_opts import (
    TrackOpts, TrackOptsError, parse_token, resolve_track_opts,
)
from app.services.transcoder import _build_ffmpeg_args, out_dir_for


# ---------------------------------------------------------------------------
# track_opts token
# ---------------------------------------------------------------------------
def test_token_round_trip():
    o = TrackOpts(audio_index=2, burn_sub_index=5, max_height=720)
    assert o.to_token() == "a2-s5-q720"
    assert parse_token("a2-s5-q720") == o
    assert parse_token("") == TrackOpts()
    assert parse_token(None).empty


@pytest.mark.parametrize("bad", ["x1", "a", "q999", "q360", "s1-a2", "a01", "a2--q720", "a2q720"])
def test_token_rejects_non_canonical(bad):
    with pytest.raises(TrackOptsError):
        parse_token(bad)


STREAMS = {
    "audio": [
        {"index": 1, "codec": "eac3", "default": True},
        {"index": 2, "codec": "aac", "default": False},
    ],
    "subtitles": [
        {"index": 3, "codec": "subrip"},
        {"index": 4, "codec": "hdmv_pgs_subtitle"},
    ],
}


def test_resolve_alternate_audio_forces_map():
    o = resolve_track_opts(audio_track_index=2, subtitle=None, quality=None,
                           source_height=1080, streams=STREAMS)
    assert o.to_token() == "a2"


def test_resolve_default_audio_is_noop():
    o = resolve_track_opts(audio_track_index=1, subtitle="off", quality="original",
                           source_height=1080, streams=STREAMS)
    assert o.empty


def test_resolve_text_sub_never_transcodes_image_sub_burns():
    assert resolve_track_opts(audio_track_index=None, subtitle=3, quality=None,
                              source_height=1080, streams=STREAMS).empty
    assert resolve_track_opts(audio_track_index=None, subtitle=4, quality=None,
                              source_height=1080, streams=STREAMS).to_token() == "s4"
    assert resolve_track_opts(audio_track_index=None, subtitle="burn", quality=None,
                              source_height=1080, streams=STREAMS).to_token() == "s4"


def test_resolve_quality_ceiling_only_below_source():
    assert resolve_track_opts(audio_track_index=None, subtitle=None, quality="720p",
                              source_height=1080, streams=None).to_token() == "q720"
    assert resolve_track_opts(audio_track_index=None, subtitle=None, quality="1080p",
                              source_height=720, streams=None).empty


def test_resolve_unknown_audio_index_dropped():
    assert resolve_track_opts(audio_track_index=9, subtitle=None, quality=None,
                              source_height=1080, streams=STREAMS).empty


# ---------------------------------------------------------------------------
# ffmpeg argv + cache layout
# ---------------------------------------------------------------------------
def _v() -> Variant:
    return Variant("medium", 720, 3000, 128)


def test_argv_unchanged_without_opts(tmp_path):
    a = _build_ffmpeg_args(Path("in.mkv"), _v(), tmp_path, nvenc=False)
    b = _build_ffmpeg_args(Path("in.mkv"), _v(), tmp_path, nvenc=False, opts=TrackOpts())
    assert a == b
    assert "-map" not in a


def test_argv_maps_selected_audio(tmp_path):
    args = _build_ffmpeg_args(Path("in.mkv"), _v(), tmp_path, nvenc=True,
                              opts=parse_token("a2"))
    joined = " ".join(args)
    assert "-map 0:v:0" in joined
    assert "-map 0:2" in joined
    assert "scale_cuda=-2:720" in joined


def test_argv_burns_image_subtitle_on_cpu(tmp_path):
    args = _build_ffmpeg_args(Path("in.mkv"), _v(), tmp_path, nvenc=True,
                              opts=parse_token("s4"))
    joined = " ".join(args)
    assert "-hwaccel_output_format" not in args
    fc = args[args.index("-filter_complex") + 1]
    assert fc == "[0:v:0][0:4]overlay,scale=-2:720[vout]"
    assert "-map [vout]" in joined
    assert "scale_cuda" not in joined
    assert "-sn" in args


def test_out_dir_separates_options():
    mid = uuid.uuid4()
    assert out_dir_for(mid, "high", 0) != out_dir_for(mid, "high", 0, "a2")
    assert out_dir_for(mid, "high", 0, "a2").parent.name == "high_a2"
    assert out_dir_for(mid, "high", 0, "a2").name == "t0"


def test_signature_binds_options():
    uid, mid = uuid.uuid4(), uuid.uuid4()
    p = sign_stream_url_params(uid, mid, offset_bucket=0, opts="a2")
    assert p["o"] == "a2"
    assert verify_stream_url_params(str(uid), str(mid), p["exp"], p["sig"], 0, "a2")
    assert not verify_stream_url_params(str(uid), str(mid), p["exp"], p["sig"], 0, "a3")
    assert not verify_stream_url_params(str(uid), str(mid), p["exp"], p["sig"], 0, "")
    plain = sign_stream_url_params(uid, mid)
    assert "o" not in plain
    assert verify_stream_url_params(str(uid), str(mid), plain["exp"], plain["sig"], 0)


# ---------------------------------------------------------------------------
# stream/start
# ---------------------------------------------------------------------------
@pytest.fixture()
def h264_movie(db_session, tmp_path):
    p = tmp_path / "movie.mp4"
    p.write_bytes(b"x")
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
        container="mp4", video_codec="h264", audio_codec="aac",
        scan_state=ScanState.ready, duration_sec=100, height=1080,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


@pytest.fixture()
def probe(monkeypatch):
    monkeypatch.setattr(media_streams, "probe_streams", lambda path, timeout=30.0: STREAMS)


def _q(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_stream_start_default_is_direct(client, h264_movie):
    r = client.post("/api/stream/start", json={"file_id": str(h264_movie.id)})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "direct"
    assert r.json()["track_opts"] is None
    assert "o" not in _q(r.json()["url"])


def test_stream_start_alt_audio_forces_hls_with_signed_opts(client, h264_movie, probe):
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_movie.id), "audio_track_index": 2,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hls"
    assert "/master.m3u8" in body["url"]
    q = _q(body["url"])
    assert q["o"] == "a2" and body["track_opts"] == "a2"
    assert verify_stream_url_params(q["uid"], str(h264_movie.id), int(q["exp"]),
                                    q["sig"], int(q["t"]), q["o"])


def test_stream_start_quality_and_burn(client, h264_movie, probe):
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_movie.id), "subtitle": "burn", "quality": "480p",
    })
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hls"
    assert _q(r.json()["url"])["o"] == "s4-q480"


def test_stream_start_text_subtitle_stays_direct(client, h264_movie, probe):
    r = client.post("/api/stream/start", json={"file_id": str(h264_movie.id), "subtitle": 3})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "direct"


# ---------------------------------------------------------------------------
# signed art_url on stream/start (lock-screen artwork)
# ---------------------------------------------------------------------------
def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def test_stream_start_returns_signed_absolute_art_url(client, db_session, tmp_path, monkeypatch):
    from app.models.user import User
    monkeypatch.setattr(settings, "art_root", tmp_path)
    owner = User(username="art-owner", display_name="O", password_hash="x",
                 role="member", is_active=True)
    db_session.add(owner)
    artist = Artist(name="A")
    db_session.add(artist)
    db_session.flush()
    album = Album(artist_id=artist.id, title="Alb")
    db_session.add(album)
    db_session.flush()
    t = Track(album_id=album.id, title="T", track_number=1, duration_sec=10)
    db_session.add(t)
    db_session.flush()
    p = tmp_path / "t.flac"
    p.write_bytes(b"x")
    mf = MediaFile(kind=MediaKind.track, ref_id=t.id, path=str(p), container="flac",
                   scan_state=ScanState.ready, duration_sec=10)
    db_session.add(mf)
    art_service.save_upload_bytes(
        db_session, entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER,
        data=_png(), set_by_user_id=owner.id, source_kind="upload", source_ref="c.png",
    )
    db_session.commit()

    r = client.post("/api/stream/start", json={"file_id": str(mf.id)},
                    headers={"host": "api.example.com", "x-forwarded-proto": "https"})
    assert r.status_code == 200, r.text
    art = r.json()["art_url"]
    assert art.startswith(f"https://api.example.com/api/art/album/{album.id}/cover?")
    q = _q(art)
    assert verify_art_url_params("album", album.id, "cover", q["uid"], int(q["exp"]), q["sig"])


def test_stream_start_art_url_null_without_art(client, h264_movie):
    r = client.post("/api/stream/start", json={"file_id": str(h264_movie.id)})
    assert r.json()["art_url"] is None


# ---------------------------------------------------------------------------
# gateway honors the token
# ---------------------------------------------------------------------------
@pytest.fixture()
def gateway(db_session):
    from fastapi.testclient import TestClient
    from app import stream as gw

    def _db():
        yield db_session

    gw.app.dependency_overrides[gw.get_db] = _db
    try:
        c = TestClient(gw.app)
        yield c
        c.close()
    finally:
        gw.app.dependency_overrides.clear()


@pytest.fixture()
def hevc_1080(db_session, tmp_path):
    p = tmp_path / "m.mkv"
    p.write_bytes(b"x")
    mf = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
                   container="mkv", video_codec="hevc", audio_codec="eac3",
                   scan_state=ScanState.ready, duration_sec=100, height=1080)
    db_session.add(mf)
    db_session.commit()
    return mf


def test_gateway_master_capped_and_propagates_opts(gateway, hevc_1080):
    uid = uuid.uuid4()
    p = sign_stream_url_params(uid, hevc_1080.id, opts="a2-q720")
    r = gateway.get(f"/stream/hls/{hevc_1080.id}/master.m3u8", params={
        "uid": p["uid"], "exp": p["exp"], "sig": p["sig"], "t": 0, "o": "a2-q720",
    })
    assert r.status_code == 200, r.text
    uris = [l for l in r.text.splitlines() if l.startswith("/stream/")]
    assert uris and all("o=a2-q720" in u for u in uris)
    assert not any("/high/" in u for u in uris)


def test_gateway_rejects_opts_not_in_signature(gateway, hevc_1080):
    uid = uuid.uuid4()
    p = sign_stream_url_params(uid, hevc_1080.id)
    r = gateway.get(f"/stream/hls/{hevc_1080.id}/master.m3u8", params={
        "uid": p["uid"], "exp": p["exp"], "sig": p["sig"], "t": 0, "o": "a2",
    })
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# On Deck
# ---------------------------------------------------------------------------
def _eps(n, season=1):
    return [EpisodeRef(i, season, i, f"f{i}") for i in range(1, n + 1)]


def test_next_episode_rolls_forward_after_completed():
    eps = _eps(4)
    prog = {"f1": ProgressRef(1200, True), "f2": ProgressRef(1300, True)}
    assert next_episode(eps, prog).episode_number == 3


def test_next_episode_prefers_in_progress():
    eps = _eps(4)
    prog = {"f1": ProgressRef(1200, True), "f3": ProgressRef(300, False)}
    assert next_episode(eps, prog).episode_number == 3


def test_next_episode_none_when_finished_or_unstarted():
    eps = _eps(2)
    assert next_episode(eps, {"f1": ProgressRef(1, True), "f2": ProgressRef(1, True)}) is None
    assert next_episode(eps, {}) is None


def test_next_episode_crosses_season_and_skips_specials():
    eps = [EpisodeRef("sp", 0, 1, "f0")] + _eps(2, 1) + [EpisodeRef("s2e1", 2, 1, "g1")]
    prog = {"f1": ProgressRef(1, True), "f2": ProgressRef(1, True)}
    assert next_episode(eps, prog).episode_id == "s2e1"


def test_on_deck_endpoint(client, db_session):
    from app.api.deps import current_user
    from app.main import app
    user = app.dependency_overrides[current_user]()
    db_session.merge(user)
    s = Series(title="Show")
    db_session.add(s)
    db_session.flush()
    files = []
    for i in (1, 2, 3):
        e = Episode(series_id=s.id, season_number=1, episode_number=i, title=f"E{i}")
        db_session.add(e)
        db_session.flush()
        mf = MediaFile(kind=MediaKind.episode, ref_id=e.id, path=f"/x/{i}.mkv",
                       container="mkv", scan_state=ScanState.ready, duration_sec=1500)
        db_session.add(mf)
        db_session.flush()
        files.append(mf)
    now = datetime.now(timezone.utc)
    db_session.add(WatchProgress(user_id=user.id, media_file_id=files[0].id,
                                 position_sec=1500, duration_sec=1500,
                                 completed_at=now, updated_at=now))
    db_session.commit()

    r = client.get("/api/on-deck")
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == str(s.id)
    assert items[0]["episode_number"] == 2
    assert items[0]["media_file_id"] == str(files[1].id)
    assert items[0]["position_sec"] == 0


# ---------------------------------------------------------------------------
# Up Next: next episode lookup for the credits countdown (criterion 37)
# ---------------------------------------------------------------------------
def _show(db_session, eps):
    s = Series(title="Chain")
    db_session.add(s)
    db_session.flush()
    files = {}
    for season, num, ready in eps:
        e = Episode(series_id=s.id, season_number=season, episode_number=num, title=f"T{num}")
        db_session.add(e)
        db_session.flush()
        mf = MediaFile(kind=MediaKind.episode, ref_id=e.id, path=f"/x/{season}-{num}.mkv",
                       container="mkv",
                       scan_state=ScanState.ready if ready else ScanState.missing,
                       duration_sec=1500)
        db_session.add(mf)
        db_session.flush()
        files[(season, num)] = mf
    db_session.commit()
    return s, files


def test_next_episode_endpoint_skips_missing_and_crosses_seasons(client, db_session):
    s, f = _show(db_session, [(1, 1, True), (1, 2, False), (2, 1, True)])
    r = client.get(f"/api/media-files/{f[(1, 1)].id}/next-episode")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["media_file_id"] == str(f[(2, 1)].id)
    assert body["season_number"] == 2 and body["episode_number"] == 1
    assert body["title"].startswith("S02E01")


def test_next_episode_endpoint_null_at_end_and_for_movies(client, db_session, h264_movie):
    s, f = _show(db_session, [(1, 1, True)])
    assert client.get(f"/api/media-files/{f[(1, 1)].id}/next-episode").json() is None
    assert client.get(f"/api/media-files/{h264_movie.id}/next-episode").json() is None


# ---------------------------------------------------------------------------
# "Date added" sort key on library lists (criterion 39)
# ---------------------------------------------------------------------------
def test_library_lists_expose_created_at(client, db_session):
    from app.models.movie import Movie
    m = Movie(title="Added")
    db_session.add(m)
    db_session.flush()
    db_session.add(MediaFile(kind=MediaKind.movie, ref_id=m.id, path="/x/a.mp4",
                             container="mp4", scan_state=ScanState.ready))
    artist = Artist(name="Ar")
    db_session.add(artist)
    db_session.flush()
    db_session.add(Album(artist_id=artist.id, title="Al"))
    db_session.add(Series(title="Se"))
    db_session.commit()
    for path in ("/api/movies", "/api/albums", "/api/series"):
        r = client.get(path, params={"include_pending": True})
        assert r.status_code == 200, (path, r.text)
        rows = r.json()
        assert rows, path
        assert all("created_at" in row for row in rows), path


# ---------------------------------------------------------------------------
# Signed download URL (criterion 42/43: downloads never depend on a bearer
# that can expire mid-transfer)
# ---------------------------------------------------------------------------
def test_download_url_signed_and_fetchable_without_bearer(client, db_session, tmp_path):
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app

    p = tmp_path / "song.flac"
    p.write_bytes(b"fLaC-bytes")
    mf = MediaFile(kind=MediaKind.track, ref_id=uuid.uuid4(), path=str(p),
                   container="flac", scan_state=ScanState.ready, duration_sec=5)
    db_session.add(mf)
    db_session.commit()

    r = client.get(f"/api/media-files/{mf.id}/download-url",
                   headers={"host": "api.example.com", "x-forwarded-proto": "https"})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith(f"https://api.example.com/api/media-files/{mf.id}/download?")
    assert r.json()["container"] == "flac"

    # Fetch with no bearer: the signed query alone authorizes it.
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = saved[get_db]
    try:
        anon = TestClient(app)
        q = urlparse(url)
        got = anon.get(f"{q.path}?{q.query}")
        assert got.status_code == 200, got.text
        assert got.content == b"fLaC-bytes"
        anon.close()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_download_url_409_for_video_that_cannot_be_offered(client, hevc_1080):
    r = client.get(f"/api/media-files/{hevc_1080.id}/download-url")
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "not_available_offline"


# ---------------------------------------------------------------------------
# Downloads of files with non-latin-1 names (the real offline-playback blocker:
# "01 − Human.flac" made the Content-Disposition header raise -> 500)
# ---------------------------------------------------------------------------
def test_download_non_latin1_filename(client, db_session, tmp_path):
    from fastapi.testclient import TestClient
    from app.api.deps import get_db
    from app.main import app

    p = tmp_path / "01 − Human é.flac"
    p.write_bytes(b"fLaC-unicode")
    mf = MediaFile(kind=MediaKind.track, ref_id=uuid.uuid4(), path=str(p),
                   container="flac", scan_state=ScanState.ready, duration_sec=5)
    db_session.add(mf)
    db_session.commit()
    url = client.get(f"/api/media-files/{mf.id}/download-url").json()["url"]
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = saved[get_db]
    try:
        anon = TestClient(app)
        q = urlparse(url)
        got = anon.get(f"{q.path}?{q.query}")
        assert got.status_code == 200, got.text
        assert got.content == b"fLaC-unicode"
        cd = got.headers["content-disposition"]
        assert 'filename="01 _ Human _.flac"' in cd
        assert "filename*=UTF-8''01%20%E2%88%92%20Human%20%C3%A9.flac" in cd
        anon.close()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_progress_upsert_recovers_from_insert_race(client, db_session, h264_movie, monkeypatch):
    # Simulate the race: the first commit fails with a unique violation after
    # another request inserted the row; the handler must update, not 500.
    from sqlalchemy.exc import IntegrityError
    from app.api.deps import current_user
    from app.main import app

    user = app.dependency_overrides[current_user]()
    db_session.merge(user)
    db_session.commit()
    real_commit = db_session.commit
    state = {"n": 0}

    def flaky_commit():
        state["n"] += 1
        if state["n"] == 1:
            db_session.rollback()
            db_session.add(WatchProgress(user_id=user.id, media_file_id=h264_movie.id,
                                         position_sec=5, duration_sec=100))
            real_commit()
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)
    r = client.put(f"/api/progress/{h264_movie.id}", json={"position_sec": 42, "duration_sec": 100})
    assert r.status_code == 200, r.text
    assert r.json()["position_sec"] == 42


def test_stream_start_reports_hls_offset(client, h264_movie):
    """A resumed HLS stream starts its own timeline at 0; the response tells
    the player where that 0 sits in the source."""
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_movie.id), "quality": "480p", "resume_sec": 47,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hls"
    assert body["offset_sec"] == 40 and _q(body["url"])["t"] == "40"
    # Direct play seeks client-side; its offset is always 0.
    r = client.post("/api/stream/start", json={"file_id": str(h264_movie.id), "resume_sec": 47})
    assert r.json()["mode"] == "direct" and r.json()["offset_sec"] == 0
