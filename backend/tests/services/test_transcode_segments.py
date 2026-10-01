"""Unit tests for the HLS segment completeness gate and the resume-aware
ffmpeg argv builder.

No ffmpeg process is spawned. Everything operates on a tmp_path cache dir and
pure argv construction, so these run fast and offline.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.services.playback import VARIANT_LADDER
from app.services.transcoder import _build_ffmpeg_args, out_dir_for
from app.stream import segment_is_complete


def _variant():
    # Any real variant; the argv shape under test is identical across the ladder.
    return VARIANT_LADDER[0]


def _write_playlist(out_dir: Path, *, endlist: bool) -> None:
    body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:6.000,\nseg_00000.ts\n"
    if endlist:
        body += "#EXT-X-ENDLIST\n"
    (out_dir / "index.m3u8").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Completeness gate
# ---------------------------------------------------------------------------
def test_segment_complete_when_next_segment_exists(tmp_path: Path) -> None:
    (tmp_path / "seg_00000.ts").write_bytes(b"x")
    (tmp_path / "seg_00001.ts").write_bytes(b"y")
    # seg 0 is finalized because ffmpeg has already opened seg 1.
    assert segment_is_complete(tmp_path, 0) is True


def test_segment_incomplete_when_alone_and_no_endlist(tmp_path: Path) -> None:
    (tmp_path / "seg_00000.ts").write_bytes(b"x")
    _write_playlist(tmp_path, endlist=False)
    # No successor and the encode is still open: a partial .ts is never served.
    assert segment_is_complete(tmp_path, 0) is False


def test_last_segment_complete_with_endlist(tmp_path: Path) -> None:
    (tmp_path / "seg_00000.ts").write_bytes(b"x")
    _write_playlist(tmp_path, endlist=True)
    # Final segment has no successor; ENDLIST proves the encode finished.
    assert segment_is_complete(tmp_path, 0) is True


def test_segment_missing_is_incomplete(tmp_path: Path) -> None:
    assert segment_is_complete(tmp_path, 5) is False


# ---------------------------------------------------------------------------
# argv builder
# ---------------------------------------------------------------------------
def test_cold_start_argv_is_unchanged(tmp_path: Path) -> None:
    args = _build_ffmpeg_args(Path("in.mkv"), _variant(), tmp_path, nvenc=False)
    # Cold start (bucket 0) stays bit-identical to before: no seek, no
    # start_number, canonical index.
    assert "-start_number" not in args
    assert "-ss" not in args
    assert str(tmp_path / "index.m3u8") in args
    assert str(tmp_path / "index.part.m3u8") not in args


def test_resume_argv_has_start_number_and_side_playlist(tmp_path: Path) -> None:
    args = _build_ffmpeg_args(
        Path("in.mkv"), _variant(), tmp_path, nvenc=False,
        offset_bucket=300, start_number=50, playlist_name="index.part.m3u8",
    )
    assert "-start_number" in args
    assert args[args.index("-start_number") + 1] == "50"
    # offset_bucket drives the input seek.
    assert "-ss" in args
    assert args[args.index("-ss") + 1] == "300"
    # The muxer index goes to the side file so index.m3u8 is not clobbered.
    assert str(tmp_path / "index.part.m3u8") in args
    assert str(tmp_path / "index.m3u8") not in args


# ---------------------------------------------------------------------------
# Cache dir helper
# ---------------------------------------------------------------------------
def test_out_dir_for_is_deterministic() -> None:
    mid = uuid.UUID("65a0d194-339b-410b-9673-3f4cd5d6fb34")
    d1 = out_dir_for(mid, "medium", 0)
    d2 = out_dir_for(mid, "medium", 0)
    assert d1 == d2
    assert d1.name == "t0"
    assert d1.parent.name == "medium"
    assert d1.parent.parent.name == str(mid)
