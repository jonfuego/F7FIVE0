"""Video fast-start fixes: cached stream probes and complete-only segment serving."""
from __future__ import annotations

import os
from pathlib import Path

from app.services import media_streams


def test_probe_streams_cached_per_file_version(tmp_path: Path, monkeypatch) -> None:
    media_streams.clear_probe_cache()
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x" * 10)
    calls = []

    def fake_run(path, timeout):
        calls.append(path)
        return {"subtitles": [], "audio": [{"index": 1, "codec": "aac"}]}

    monkeypatch.setattr(media_streams, "_run_probe", fake_run)
    a = media_streams.probe_streams(str(f))
    b = media_streams.probe_streams(str(f))
    assert a == b and len(calls) == 1

    # A changed file (new size + mtime) is probed again.
    f.write_bytes(b"x" * 20)
    os.utime(f, (1_900_000_000, 1_900_000_000))
    media_streams.probe_streams(str(f))
    assert len(calls) == 2


def test_probe_failures_are_not_cached(tmp_path: Path, monkeypatch) -> None:
    media_streams.clear_probe_cache()
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x")
    results = [None, {"subtitles": [], "audio": []}]
    monkeypatch.setattr(media_streams, "_run_probe", lambda path, timeout: results.pop(0))
    assert media_streams.probe_streams(str(f)) is None
    assert media_streams.probe_streams(str(f)) == {"subtitles": [], "audio": []}


def test_segment_wait_uses_completeness_gate() -> None:
    # The slow path must wait on segment_is_complete, never bare existence,
    # so a half-written .ts is not served.
    src = (Path(__file__).resolve().parents[2] / "app" / "stream.py").read_text(encoding="utf-8")
    slow = src.split("seg_path = job.out_dir / segment", 1)[1].split("job.touch()", 1)[0]
    assert "segment_is_complete(job.out_dir, seg_index)" in slow
    assert "while not seg_path.exists()" not in slow
