"""A Cast receiver's stream has its own encode identity and a single rung.

The Default Media Receiver hops between the master playlist's rungs, and each
hop used to stop the encode the sender's own player (or the receiver itself)
was still reading, because the transcode registry could not tell a cast stream
from the sender's stream of the same file. The `c` part of the track-options
token now separates them in the signature, the registry key, the cache dir and
the ladder. Uses the real TranscodeManager with ffmpeg stubbed.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services import transcoder
from app.services.playback import VARIANT_LADDER
from app.services.security import sign_stream_url_params, verify_stream_url_params
from app.services.track_opts import TrackOpts, TrackOptsError, parse_token

CAST = TrackOpts(cast=True).to_token()


class FakeProc:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def manager(tmp_path: Path, monkeypatch):
    procs: list[FakeProc] = []

    def fake_start(self, user_id, media_file_id, variant, source_path, offset_bucket=0, *, opts="", **_kw):
        proc = FakeProc()
        procs.append(proc)
        return transcoder.TranscodeJob(
            user_id=user_id, media_file_id=media_file_id, variant=variant,
            source_path=source_path, out_dir=tmp_path / f"{variant.label}_{opts}", proc=proc,
            offset_bucket=offset_bucket, opts=opts,
        )

    monkeypatch.setattr(transcoder.TranscodeManager, "_start", fake_start)
    monkeypatch.setattr(transcoder, "_close_session_row", lambda _rid: None)
    return transcoder.TranscodeManager(), procs


def _v(label: str):
    return next(v for v in VARIANT_LADDER if v.label == label)


# (a) a cast job and a play job are not siblings
def test_cast_and_play_jobs_both_keep_running(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    play = mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv")
    cast = mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv", opts=CAST)
    assert play is not cast
    assert len(procs) == 2
    assert not any(p.terminated for p in procs)
    # Starting the play job again later does not stop the cast job either.
    again = mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")
    assert again is not play  # the play job was replaced by its own sibling rule
    assert cast.is_running() and not procs[1].terminated


def test_cast_marker_survives_quality_ceiling_and_picks(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv", opts="a2-q720")
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv", opts="a2-q720-c")
    assert not any(p.terminated for p in procs)


# (b) two play jobs with different variants still replace each other
def test_play_jobs_still_replace_each_other(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv")
    mgr.get_or_start(uid, mid, _v("low"), tmp_path / "f.mkv")
    assert procs[0].terminated
    assert not procs[1].terminated


def test_cast_jobs_replace_each_other_within_cast(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv", opts=CAST)
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv", opts=TrackOpts(max_height=720, cast=True).to_token())
    assert procs[0].terminated
    assert not procs[1].terminated


# (c) the master playlist for a cast stream has exactly one rung
@pytest.mark.parametrize("nvenc", [True, False])
@pytest.mark.parametrize("height", [1080, 2160, 720])
def test_cast_master_playlist_has_one_stream_inf(monkeypatch, nvenc, height) -> None:
    from app.stream import hls_master

    monkeypatch.setattr(settings, "nvenc_enabled", nvenc)
    mf = SimpleNamespace(
        id=uuid.uuid4(), height=height, kind=MediaKind.movie,
        video_codec="hevc", audio_codec="aac", container="mkv",
    )
    body = hls_master(mf=mf, uid="u", exp=1, sig="s", t=0, o=CAST, sid="x").body.decode()
    assert body.count("#EXT-X-STREAM-INF") == 1


def test_cast_rung_is_the_highest_within_the_ceiling(monkeypatch) -> None:
    from app.stream import _variants_for

    monkeypatch.setattr(settings, "nvenc_enabled", True)
    mf = SimpleNamespace(height=1080)
    assert [v.label for v in _variants_for(mf, CAST)] == ["high"]
    assert [v.label for v in _variants_for(mf, "q720-c")] == ["medium"]
    assert [v.label for v in _variants_for(mf, "q480-c")] == ["low"]
    # A play stream keeps the full ladder.
    assert len(_variants_for(mf, "")) == 3


# (d) a cast URL and a play URL sign differently, and each verifies
def test_cast_and_play_urls_sign_differently_and_each_verifies() -> None:
    uid, mid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    play = sign_stream_url_params(uid, mid, sid)
    cast = sign_stream_url_params(uid, mid, sid, opts=CAST)
    assert play["sig"] != cast["sig"]
    assert cast["o"] == CAST and "o" not in play
    assert verify_stream_url_params(
        play["uid"], play["mid"], play["exp"], play["sig"], play["sid"], play["t"], "",
    )
    assert verify_stream_url_params(
        cast["uid"], cast["mid"], cast["exp"], cast["sig"], cast["sid"], cast["t"], CAST,
    )
    # The marker cannot be added to a play URL or stripped from a cast URL.
    assert not verify_stream_url_params(
        play["uid"], play["mid"], play["exp"], play["sig"], play["sid"], play["t"], CAST,
    )
    assert not verify_stream_url_params(
        cast["uid"], cast["mid"], cast["exp"], cast["sig"], cast["sid"], cast["t"], "",
    )


# (e) a URL without the flag verifies unchanged
def test_url_without_the_flag_verifies_unchanged() -> None:
    uid, mid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for opts in ("", "a2", "q720", "a2-s4-q480"):
        p = sign_stream_url_params(uid, mid, sid, opts=opts)
        assert verify_stream_url_params(
            p["uid"], p["mid"], p["exp"], p["sig"], p["sid"], p["t"], opts,
        )
        assert parse_token(opts).cast is False


def test_token_grammar_and_argv() -> None:
    assert TrackOpts(cast=True).to_token() == "c"
    assert TrackOpts(audio_index=2, max_height=720, cast=True).to_token() == "a2-q720-c"
    assert parse_token("a2-q720-c") == TrackOpts(audio_index=2, max_height=720, cast=True)
    assert parse_token("c").cast and parse_token("c").empty
    for bad in ("cc", "c-q720", "q720c", "x"):
        with pytest.raises(TrackOptsError):
            parse_token(bad)
    # A cast-only token builds the same ffmpeg command as no token.
    a = transcoder._build_ffmpeg_args(Path("in.mkv"), _v("medium"), Path("out"), nvenc=False)
    b = transcoder._build_ffmpeg_args(
        Path("in.mkv"), _v("medium"), Path("out"), nvenc=False, opts=parse_token("c"),
    )
    assert a == b
    # And its segments live apart from the play stream's.
    mid = uuid.uuid4()
    assert transcoder.out_dir_for(mid, "high", 0, "c") != transcoder.out_dir_for(mid, "high", 0, "")


# stream/start sets the marker for purpose=cast, and only then
@pytest.fixture()
def hevc_movie(db_session, tmp_path):
    p = tmp_path / "movie.mkv"
    p.write_bytes(b"x")
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
        container="mkv", video_codec="hevc", audio_codec="eac3",
        scan_state=ScanState.ready, duration_sec=100, height=1080,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


def _q(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_stream_start_marks_only_cast_starts(client, hevc_movie) -> None:
    play = client.post("/api/stream/start", json={"file_id": str(hevc_movie.id)})
    cast = client.post(
        "/api/stream/start", json={"file_id": str(hevc_movie.id), "purpose": "cast"},
    )
    assert play.status_code == 200 and cast.status_code == 200, (play.text, cast.text)
    assert play.json()["mode"] == "hls" and cast.json()["mode"] == "hls"
    assert "o" not in _q(play.json()["url"]) and play.json()["track_opts"] is None
    qc = _q(cast.json()["url"])
    assert qc["o"] == "c" and cast.json()["track_opts"] == "c"
    assert verify_stream_url_params(
        qc["uid"], str(hevc_movie.id), int(qc["exp"]), qc["sig"], qc["sid"], int(qc["t"]), qc["o"],
    )


def test_cast_start_keeps_quality_ceiling(client, hevc_movie, monkeypatch) -> None:
    monkeypatch.setattr(settings, "nvenc_enabled", True)
    r = client.post("/api/stream/start", json={
        "file_id": str(hevc_movie.id), "purpose": "cast", "quality": "720p",
    })
    assert r.status_code == 200, r.text
    assert _q(r.json()["url"])["o"] == "q720-c"


def test_cast_start_of_a_direct_file_is_not_marked(client, db_session, tmp_path) -> None:
    p = tmp_path / "movie.mp4"
    p.write_bytes(b"x")
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
        container="mp4", video_codec="h264", audio_codec="aac",
        scan_state=ScanState.ready, duration_sec=100, height=1080,
    )
    db_session.add(mf)
    db_session.commit()
    r = client.post("/api/stream/start", json={"file_id": str(mf.id), "purpose": "cast"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "direct"
    assert "o" not in _q(r.json()["url"])
