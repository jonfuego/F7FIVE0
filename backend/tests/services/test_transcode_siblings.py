"""A quality switch stops the viewer's other variant encodes right away."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services import transcoder
from app.services.playback import VARIANT_LADDER


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
            source_path=source_path, out_dir=tmp_path / variant.label, proc=proc,
            offset_bucket=offset_bucket, opts=opts,
        )

    monkeypatch.setattr(transcoder.TranscodeManager, "_start", fake_start)
    monkeypatch.setattr(transcoder, "_close_session_row", lambda _rid: None)
    return transcoder.TranscodeManager(), procs


def _v(label: str):
    return next(v for v in VARIANT_LADDER if v.label == label)


def test_switch_stops_previous_variant(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    medium = mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")
    low = mgr.get_or_start(uid, mid, _v("low"), tmp_path / "f.mkv")
    assert procs[0].terminated, "medium ffmpeg should stop when low starts"
    assert low.is_running()
    assert mgr.get(uid, mid, "medium") is None
    assert medium is not low


def test_same_variant_reuses_job(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    a = mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")
    b = mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")
    assert a is b and len(procs) == 1 and not procs[0].terminated


def test_other_viewers_and_files_untouched(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    u1, u2, m1, m2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(u1, m1, _v("medium"), tmp_path / "f.mkv")   # procs[0]
    mgr.get_or_start(u2, m1, _v("medium"), tmp_path / "f.mkv")   # other viewer
    mgr.get_or_start(u1, m2, _v("medium"), tmp_path / "g.mkv")   # other file
    mgr.get_or_start(u1, m1, _v("low"), tmp_path / "f.mkv", opts="a2")  # other track picks
    assert not any(p.terminated for p in procs)


def test_new_start_position_replaces_old_encode(manager, tmp_path: Path) -> None:
    """A quality switch mid-movie resumes at a new offset bucket; the encode
    from the old position must still stop."""
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")
    mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv", offset_bucket=30, opts="q1080")
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv", offset_bucket=40, opts="q720")
    assert procs[0].terminated and procs[1].terminated and not procs[2].terminated


def test_finished_sibling_keeps_its_cache(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")
    procs[0].returncode = 0          # medium finished encoding the whole file
    (tmp_path / "medium").mkdir()
    (tmp_path / "medium" / "index.m3u8").write_text("#EXTM3U\n")
    mgr.get_or_start(uid, mid, _v("low"), tmp_path / "f.mkv")
    assert not procs[0].terminated
    assert mgr.get(uid, mid, "medium") is not None


def test_quality_change_via_new_stream_stops_old_encode(manager, tmp_path: Path) -> None:
    """CPU-only servers change quality by re-requesting the stream with a `q`
    ceiling, so the new job differs only in its quality token."""
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv")              # default 720p
    mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv", opts="q1080")  # viewer picks 1080p
    assert procs[0].terminated


def test_different_audio_pick_is_not_a_sibling(manager, tmp_path: Path) -> None:
    mgr, procs = manager
    uid, mid = uuid.uuid4(), uuid.uuid4()
    mgr.get_or_start(uid, mid, _v("medium"), tmp_path / "f.mkv", opts="a2")
    mgr.get_or_start(uid, mid, _v("high"), tmp_path / "f.mkv", opts="a3-q1080")
    assert not procs[0].terminated
