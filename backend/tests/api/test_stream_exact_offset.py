"""Exact-second landing on a bucketed HLS resume (item 8d, criterion 22).

`_quantize_offset` buckets the encode start so one movie resumed a second or
two apart shares one ffmpeg session. That means the HLS timeline starts at the
bucket boundary, up to OFFSET_BUCKET_SEC-1 seconds before the second the user
asked for. stream/start now reports:

  offset_sec          - the TRUE source position the caller requested
  timeline_offset_sec - the bucketed encode start (element clock 0)
  seek_within_sec      - how far to seek into the stream to hit the exact second

The client seeks seek_within_sec into the element after it loads, so the viewer
lands on the exact requested second despite the bucket.
"""
from __future__ import annotations

import uuid

import pytest

from app.api.stream import OFFSET_BUCKET_SEC, _quantize_offset
from app.models.media_file import MediaFile, MediaKind, ScanState


@pytest.fixture()
def hevc_movie(db_session, tmp_path):
    """An HEVC movie: playback.decide picks HLS, so resume offsets are bucketed
    (direct play ignores the offset)."""
    p = tmp_path / "movie.mkv"
    p.write_bytes(b"x")
    mf = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(p),
        container="mkv", video_codec="hevc", audio_codec="eac3",
        scan_state=ScanState.ready, duration_sec=3600, height=1080,
    )
    db_session.add(mf)
    db_session.commit()
    return mf


def test_quantize_offset_buckets_down():
    assert _quantize_offset(None) == 0
    assert _quantize_offset(0) == 0
    assert _quantize_offset(OFFSET_BUCKET_SEC - 1) == 0
    assert _quantize_offset(OFFSET_BUCKET_SEC + 3) == OFFSET_BUCKET_SEC


def test_bucketed_resume_lands_on_exact_second(client, hevc_movie):
    # Resume at a second that does not fall on a bucket boundary.
    requested = 45 * 60 + 13  # 45:13
    r = client.post(
        "/api/stream/start",
        json={"file_id": str(hevc_movie.id), "resume_sec": requested},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hls"

    bucket = _quantize_offset(requested)
    # The encode starts at the bucket (before the requested second)...
    assert body["timeline_offset_sec"] == bucket
    assert bucket < requested
    # ...the true source position is reported exactly as asked...
    assert body["offset_sec"] == requested
    # ...and the client seeks the remainder into the stream to land exactly.
    assert body["seek_within_sec"] == requested - bucket
    # The invariant the viewer depends on: timeline start + seek == exact second.
    assert body["timeline_offset_sec"] + body["seek_within_sec"] == requested


def test_on_bucket_resume_needs_no_seek(client, hevc_movie):
    requested = 3 * OFFSET_BUCKET_SEC  # already on a boundary
    r = client.post(
        "/api/stream/start",
        json={"file_id": str(hevc_movie.id), "resume_sec": requested},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["offset_sec"] == requested
    assert body["timeline_offset_sec"] == requested
    assert body["seek_within_sec"] == 0


def test_direct_play_reports_true_zero_offset(client, hevc_movie, db_session):
    # A direct-playable file ignores the offset entirely (client seeks via
    # Range), so all three fields are 0 even when a resume is requested.
    p_mp4 = MediaFile(
        kind=MediaKind.movie, ref_id=uuid.uuid4(), path=str(hevc_movie.path) + ".mp4",
        container="mp4", video_codec="h264", audio_codec="aac",
        scan_state=ScanState.ready, duration_sec=3600, height=1080,
    )
    db_session.add(p_mp4)
    db_session.commit()
    r = client.post(
        "/api/stream/start",
        json={"file_id": str(p_mp4.id), "resume_sec": 500},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "direct"
    assert body["offset_sec"] == 0
    assert body["timeline_offset_sec"] == 0
    assert body["seek_within_sec"] == 0
