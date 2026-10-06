"""Audio-only HLS for music the browser can't play as-is (WMA, Opus).

Before this, a WMA track went through the video transcoder: libx264 options
with no picture, cover art mapped as video, and AAC frames with backward DTS
that Chrome refused to open. The audio-only argv maps the first audio stream
only, drops video/subtitle/data, and resamples to monotonic timestamps.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.services.playback import VARIANT_LADDER
from app.services.transcoder import _build_ffmpeg_args, build_master_playlist
from app.stream import _variants_for


def _track(container: str) -> MediaFile:
    return MediaFile(
        id=uuid.uuid4(),
        kind=MediaKind.track,
        ref_id=uuid.uuid4(),
        path=f"C:/music/song.{container}",
        container=container,
        audio_codec="wmav2",
        video_codec="mjpeg",
        scan_state=ScanState.ready,
    )


def test_audio_only_argv_maps_first_audio_and_drops_video(tmp_path: Path) -> None:
    args = _build_ffmpeg_args(
        Path("C:/music/song.wma"), VARIANT_LADDER[0], tmp_path, nvenc=False,
        audio_only=True,
    )
    assert args[args.index("-map") + 1] == "0:a:0"
    assert "-vn" in args
    assert args[args.index("-af") + 1] == "aresample=async=1"
    assert args[args.index("-c:a") + 1] == "aac"
    # No video encoder or scaler on the audio path.
    assert "-c:v" not in args
    assert "-vf" not in args
    assert "-hwaccel" not in args
    assert args[args.index("-f") + 1] == "hls"


def test_audio_only_argv_respects_resume_offset(tmp_path: Path) -> None:
    args = _build_ffmpeg_args(
        Path("C:/music/song.wma"), VARIANT_LADDER[0], tmp_path, nvenc=True,
        offset_bucket=60, audio_only=True,
    )
    assert args[args.index("-ss") + 1] == "60"
    assert args.index("-ss") < args.index("-i")
    assert "-hwaccel" not in args


def test_video_argv_unchanged_by_default(tmp_path: Path) -> None:
    args = _build_ffmpeg_args(
        Path("C:/movies/m.mkv"), VARIANT_LADDER[1], tmp_path, nvenc=False,
    )
    assert args[args.index("-c:v") + 1] == "libx264"
    assert "-vn" not in args


def test_audio_master_playlist_declares_aac_only() -> None:
    mid = uuid.uuid4()
    body = build_master_playlist(mid, (VARIANT_LADDER[0],), "uid=u&sig=s",
                                 audio_only=True)
    assert 'CODECS="mp4a.40.2"' in body
    assert "RESOLUTION" not in body
    assert "avc1" not in body
    assert f"/stream/hls/{mid}/high/index.m3u8?uid=u&sig=s" in body


def test_audio_only_source_gets_a_single_rung() -> None:
    assert _variants_for(_track("wma"), "") == (VARIANT_LADDER[0],)
    assert _variants_for(_track("opus"), "") == (VARIANT_LADDER[0],)
