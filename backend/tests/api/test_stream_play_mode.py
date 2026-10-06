"""Play-mode decision for video (batch 3 item 9).

A 1080p H.264 + AAC movie in an MKV was transcoded, and on a CPU-only server
scaled down to the 720p default rung, even in a browser (Chrome) that plays
that file as-is. The web player now reports what it can play
(`client_caps`), and a file whose container and codecs it reported
direct-plays: no video re-encode. A quality pick at or above the source
height is not a bandwidth cap and no longer forces a transcode either.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services import playback

CHROME_CAPS = {
    "containers": ["mp4", "mkv", "webm"],
    "video_codecs": ["h264", "vp9", "hevc"],
    "audio_codecs": ["aac", "mp3", "opus", "flac"],
}


def _movie(db_session, tmp_path, *, container, vcodec, acodec, height=1080):
    p = tmp_path / f"movie-{uuid.uuid4().hex}.{container}"
    p.write_bytes(b"x")
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
        container=container, video_codec=vcodec, audio_codec=acodec,
        scan_state=ScanState.ready, duration_sec=5400, height=height, width=1920,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


@pytest.fixture()
def h264_aac_mkv(db_session, tmp_path):
    return _movie(db_session, tmp_path, container="mkv", vcodec="h264", acodec="aac")


def test_h264_aac_mkv_direct_plays_when_client_reports_h264_aac(client, h264_aac_mkv):
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_aac_mkv.id),
        "client_caps": CHROME_CAPS,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Direct play: the original file, no video re-encode, no rung.
    assert body["mode"] == "direct"
    assert f"/stream/direct/{h264_aac_mkv.id}?" in body["url"]
    assert body["track_opts"] is None


def test_h264_aac_mkv_without_caps_keeps_the_old_decision(client, h264_aac_mkv):
    # Older clients and the app report nothing: unchanged behavior.
    r = client.post("/api/stream/start", json={"file_id": str(h264_aac_mkv.id)})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hls"


def test_quality_at_source_height_is_not_a_cap(client, h264_aac_mkv):
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_aac_mkv.id),
        "client_caps": CHROME_CAPS,
        "quality": "1080p",
    })
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "direct"


def test_quality_below_source_height_still_transcodes(client, h264_aac_mkv):
    # A real cap (720p on a 1080p file) is honored with a transcode.
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_aac_mkv.id),
        "client_caps": CHROME_CAPS,
        "quality": "720p",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hls"
    assert "q720" in (body["track_opts"] or "")


def test_mp4_h264_aac_with_1080p_pick_direct_plays(client, db_session, tmp_path):
    mf = _movie(db_session, tmp_path, container="mp4", vcodec="h264", acodec="aac")
    r = client.post("/api/stream/start", json={"file_id": str(mf.id), "quality": "1080p"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "direct"


def test_unreported_codec_still_transcodes(client, db_session, tmp_path):
    # AC-3 audio: Chrome does not report it, so the file is transcoded.
    mf = _movie(db_session, tmp_path, container="mkv", vcodec="h264", acodec="ac3")
    r = client.post("/api/stream/start", json={"file_id": str(mf.id), "client_caps": CHROME_CAPS})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hls"


def test_cast_ignores_browser_caps(client, h264_aac_mkv):
    # The cast receiver is a different player; the browser's report does not
    # apply to it.
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_aac_mkv.id),
        "client_caps": CHROME_CAPS,
        "purpose": "cast",
    })
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hls"


def test_bad_caps_rejected(client, h264_aac_mkv):
    r = client.post("/api/stream/start", json={
        "file_id": str(h264_aac_mkv.id),
        "client_caps": {"containers": ["MKV; rm -rf"]},
    })
    assert r.status_code == 422


def test_decide_unit_h264_aac_mkv():
    mf = MediaFile(kind=MediaKind.movie, ref_id=uuid.uuid4(), path="m.mkv",
                   container="mkv", video_codec="h264", audio_codec="aac",
                   scan_state=ScanState.ready, height=1080)
    caps = playback.ClientCaps.from_lists(["mkv"], ["avc1"], ["mp4a"])
    d = playback.decide(mf, caps)
    assert d.mode == "direct"
    assert d.reason == "direct_ok_client_caps"
    assert playback.decide(mf).mode == "hls"
