"""Tests for the music-videos scanner.

Covers the pure parsing helpers and the filesystem-walk discovery
function. The DB-backed scan() entry point is exercised separately via
the API tests.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.scan_music_videos import (
    DiscoveredVideo,
    discover_release,
    find_release_cover,
    parse_disc_folder,
    parse_release_year,
    parse_track_number,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestParseDiscFolder:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Disc 01", 1),
            ("Disc 1", 1),
            ("disc 02", 2),
            ("DISC 10", 10),
            ("CD1", 1),
            ("CD 02", 2),
            ("DVD 1", 1),
            ("DVD 2", 2),
            ("BD 02", 2),
            ("Disc-01", 1),
            ("Disc_2", 2),
        ],
    )
    def test_recognized(self, name, expected):
        assert parse_disc_folder(name) == expected

    @pytest.mark.parametrize(
        "name",
        ["Bonus", "Behind The Scenes", "Extras", "Substance", "", "discography"],
    )
    def test_not_a_disc_folder(self, name):
        assert parse_disc_folder(name) is None


class TestParseTrackNumber:
    @pytest.mark.parametrize(
        "fname,expected",
        [
            ("01 - Bizarre Love Triangle.mp4", 1),
            ("1. Blue Monday.mkv", 1),
            ("1_True Faith.mp4", 1),
            ("01-Subculture.mkv", 1),
            ("12 - Round and Round.mp4", 12),
        ],
    )
    def test_leading_track_number(self, fname, expected):
        assert parse_track_number(fname) == expected

    @pytest.mark.parametrize(
        "fname",
        [
            "Bizarre Love Triangle.mp4",
            "Live in Buenos Aires.mkv",
            "Title.mp4",
        ],
    )
    def test_no_leading_number(self, fname):
        assert parse_track_number(fname) is None


class TestParseReleaseYear:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Substance 1989", 1989),
            ("Brixton Academy 1987", 1987),
            ("Live in Buenos Aires 2009", 2009),
            ("Brotherhood - Definitive Edition DVD 1 & 2", None),
            ("Substance", None),
            ("", None),
        ],
    )
    def test_year_in_title(self, title, expected):
        assert parse_release_year(title) == expected

    def test_year_anchored_to_whitespace_only(self):
        # The ADR-specified regex requires whitespace or string-boundary on
        # each side; embedded digits in dash-separated ranges or DVD codes
        # don't match. This is intentional: be strict, fall back to null.
        assert parse_release_year("Brotherhood DVD 1 & 2") is None
        assert parse_release_year("Volume 1995-1999") is None


class TestFindReleaseCover:
    def test_cover_jpg_at_root(self, tmp_path: Path):
        (tmp_path / "cover.jpg").write_bytes(b"")
        assert find_release_cover(str(tmp_path)) == str(tmp_path / "cover.jpg")

    def test_folder_png_at_root(self, tmp_path: Path):
        (tmp_path / "folder.png").write_bytes(b"")
        assert find_release_cover(str(tmp_path)) == str(tmp_path / "folder.png")

    def test_cover_preferred_over_folder(self, tmp_path: Path):
        (tmp_path / "cover.jpg").write_bytes(b"")
        (tmp_path / "folder.jpg").write_bytes(b"")
        assert find_release_cover(str(tmp_path)) == str(tmp_path / "cover.jpg")

    def test_no_cover(self, tmp_path: Path):
        assert find_release_cover(str(tmp_path)) is None

    def test_cover_not_at_root_ignored(self, tmp_path: Path):
        sub = tmp_path / "Disc 01"
        sub.mkdir()
        (sub / "cover.jpg").write_bytes(b"")
        assert find_release_cover(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Filesystem discovery
# ---------------------------------------------------------------------------
def _touch(path: Path, content: bytes = b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestDiscoverRelease:
    def test_single_disc_release(self, tmp_path: Path):
        rel_dir = tmp_path / "Substance"
        _touch(rel_dir / "01 - Ceremony.mp4")
        _touch(rel_dir / "02 - Everything's Gone Green.mp4")
        _touch(rel_dir / "03 - Temptation.mp4")

        rel = discover_release(str(rel_dir))
        assert rel.title == "Substance"
        assert rel.source_subpath == "Substance"
        assert rel.cover_path is None
        assert len(rel.videos) == 3
        for v in rel.videos:
            assert v.disc_number == 1
        # All on disc 1, track numbers parsed.
        track_nums = sorted(v.track_number for v in rel.videos)
        assert track_nums == [1, 2, 3]

    def test_two_disc_release(self, tmp_path: Path):
        rel_dir = tmp_path / "Brotherhood - Definitive Edition DVD 1 & 2"
        _touch(rel_dir / "Disc 01" / "01 - State of the Nation.mp4")
        _touch(rel_dir / "Disc 01" / "02 - Bizarre Love Triangle.mp4")
        _touch(rel_dir / "Disc 02" / "01 - True Faith.mp4")
        _touch(rel_dir / "Disc 02" / "02 - Touched By the Hand of God.mp4")

        rel = discover_release(str(rel_dir))
        discs = sorted({v.disc_number for v in rel.videos})
        assert discs == [1, 2]
        assert len(rel.videos) == 4
        # The disc-folder segment is stripped from the stored subpath.
        for v in rel.videos:
            assert "Disc 0" not in v.source_subpath
            assert v.source_subpath.endswith(".mp4")

    def test_bonus_subfolder_folds_into_disc_one(self, tmp_path: Path):
        rel_dir = tmp_path / "Substance"
        _touch(rel_dir / "Disc 01" / "01 - Ceremony.mp4")
        _touch(rel_dir / "Bonus" / "Demo.mp4")

        rel = discover_release(str(rel_dir))
        # All four (one disc-1 video, one bonus video) are on disc 1.
        bonus_videos = [v for v in rel.videos if "Bonus" in v.source_subpath]
        assert len(bonus_videos) == 1
        assert bonus_videos[0].disc_number == 1
        assert bonus_videos[0].source_subpath == "Bonus/Demo.mp4"

    def test_single_video_release(self, tmp_path: Path):
        rel_dir = tmp_path / "Live at Brixton Academy 1987"
        _touch(rel_dir / "Live at Brixton Academy.mkv")

        rel = discover_release(str(rel_dir))
        assert len(rel.videos) == 1
        v = rel.videos[0]
        assert v.disc_number == 1
        assert v.source_subpath == "Live at Brixton Academy.mkv"
        assert rel.release_year == 1987

    def test_year_in_title_parsed(self, tmp_path: Path):
        rel_dir = tmp_path / "Substance 1989"
        _touch(rel_dir / "Bizarre Love Triangle.mp4")

        rel = discover_release(str(rel_dir))
        assert rel.release_year == 1989

    def test_track_number_parsed(self, tmp_path: Path):
        rel_dir = tmp_path / "Smash"
        _touch(rel_dir / "01 - Walk This Way.mp4")
        _touch(rel_dir / "02 - Sweet Emotion.mp4")
        _touch(rel_dir / "Bonus.mp4")  # no leading track number

        rel = discover_release(str(rel_dir))
        by_title = {v.title: v.track_number for v in rel.videos}
        assert by_title["01 - Walk This Way"] == 1
        assert by_title["02 - Sweet Emotion"] == 2
        assert by_title["Bonus"] is None

    def test_cover_sidecar_detection(self, tmp_path: Path):
        rel_dir = tmp_path / "Substance"
        _touch(rel_dir / "cover.jpg", b"\x00")
        _touch(rel_dir / "01 - Ceremony.mp4")

        rel = discover_release(str(rel_dir))
        assert rel.cover_path is not None
        assert rel.cover_path.endswith("cover.jpg")
        # The cover file is image-extension and not picked up as a video.
        assert all(v.title != "cover" for v in rel.videos)

    def test_non_video_files_ignored(self, tmp_path: Path):
        rel_dir = tmp_path / "Mix"
        _touch(rel_dir / "Track.mp4")
        _touch(rel_dir / "notes.nfo")
        _touch(rel_dir / "playlist.m3u")

        rel = discover_release(str(rel_dir))
        assert len(rel.videos) == 1
        assert rel.videos[0].title == "Track"

    def test_per_video_thumb_sidecar(self, tmp_path: Path):
        rel_dir = tmp_path / "Substance"
        _touch(rel_dir / "Bizarre Love Triangle.mp4")
        _touch(rel_dir / "Bizarre Love Triangle.jpg")

        rel = discover_release(str(rel_dir))
        assert len(rel.videos) == 1
        assert rel.videos[0].thumb_path is not None
        assert rel.videos[0].thumb_path.endswith("Bizarre Love Triangle.jpg")


def test_discovered_video_dataclass_fields():
    """Lightweight smoke test that the dataclass has the documented surface."""
    v = DiscoveredVideo(
        title="X",
        source_subpath="X.mp4",
        disc_number=1,
        track_number=None,
        abs_path="/tmp/x.mp4",
        thumb_path=None,
    )
    assert v.disc_number == 1
    assert v.title == "X"


# ---------------------------------------------------------------------------
# Frame-grab thumbnails (DB-backed)
# ---------------------------------------------------------------------------
def _jpeg_bytes() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 18), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def mv_scan_env(db_session, tmp_path, monkeypatch):
    """One artist/release/video on disk, ffprobe faked, art root in tmp."""
    from app.config import settings
    from app.models.user import User
    from app.services import ffprobe, library_folders, scan_music_videos
    from app.services.art import SYSTEM_USER_ID

    db_session.add(User(
        id=SYSTEM_USER_ID, username="system", display_name="System",
        password_hash="x", role="member", is_active=False,
    ))
    db_session.commit()
    root = tmp_path / "mv"
    video = root / "New Order" / "Substance" / "01 - Blue Monday.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x" * 64)
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    monkeypatch.setattr(library_folders, "folders", lambda db, kind: [str(root)])
    monkeypatch.setattr(
        ffprobe, "probe",
        lambda path, timeout=30.0: ffprobe.ProbeResult(
            container="mp4", size_bytes=64, duration_sec=200, bitrate_kbps=1000,
            video_codec="h264", audio_codec="aac", audio_channels=2,
            width=1920, height=1080,
        ),
    )
    return scan_music_videos, video


def _fake_ffmpeg(monkeypatch, calls, rc=0):
    import subprocess

    def run(cmd, **kw):
        calls.append(cmd)
        if rc == 0:
            with open(cmd[-1], "wb") as fh:
                fh.write(_jpeg_bytes())
        return subprocess.CompletedProcess(cmd, rc, b"", b"boom")

    monkeypatch.setattr("app.services.scan_music_videos.subprocess.run", run)


def _thumb_row(db):
    from sqlalchemy import select
    from app.models.art import ArtOverride
    return db.scalars(select(ArtOverride)).first()


def test_video_without_art_gets_a_frame_grab(mv_scan_env, db_session, monkeypatch):
    scan_mod, _video = mv_scan_env
    calls: list = []
    _fake_ffmpeg(monkeypatch, calls)
    scan_mod.scan(db_session)
    row = _thumb_row(db_session)
    assert row is not None
    assert (row.entity_kind, row.role, row.source_kind) == ("music_video", "thumb", "frame")
    assert len(calls) == 1
    # ~10% of the 200 second probe duration.
    assert calls[0][calls[0].index("-ss") + 1] == "20.000"
    # A second scan does not grab again.
    scan_mod.scan(db_session)
    assert len(calls) == 1


def test_existing_art_is_never_replaced_by_a_frame(mv_scan_env, db_session, monkeypatch):
    from sqlalchemy import select
    from app.models.art import ArtOverride
    from app.models.music import MusicVideo
    scan_mod, _video = mv_scan_env
    calls: list = []
    _fake_ffmpeg(monkeypatch, calls)
    scan_mod.scan(db_session)  # creates the row (and a frame)
    mv = db_session.scalars(select(MusicVideo)).first()
    row = db_session.get(ArtOverride, ("music_video", mv.id, "thumb"))
    row.source_kind = "upload"  # admin art
    db_session.commit()
    calls.clear()
    scan_mod.scan(db_session)
    assert calls == []
    assert db_session.get(ArtOverride, ("music_video", mv.id, "thumb")).source_kind == "upload"


def test_sidecar_art_replaces_a_frame_grab(mv_scan_env, db_session, monkeypatch):
    scan_mod, video = mv_scan_env
    calls: list = []
    _fake_ffmpeg(monkeypatch, calls)
    scan_mod.scan(db_session)
    assert _thumb_row(db_session).source_kind == "frame"
    (video.parent / "01 - Blue Monday.jpg").write_bytes(_jpeg_bytes())
    scan_mod.scan(db_session)
    assert _thumb_row(db_session).source_kind == "local"


def test_ffmpeg_failure_does_not_break_the_scan(mv_scan_env, db_session, monkeypatch):
    scan_mod, _video = mv_scan_env
    _fake_ffmpeg(monkeypatch, [], rc=1)
    stats = scan_mod.scan(db_session)
    assert stats.videos_upserted == 1
    assert stats.errors == 0
    assert _thumb_row(db_session) is None


def test_ffmpeg_missing_or_timeout_does_not_break_the_scan(mv_scan_env, db_session, monkeypatch):
    import subprocess
    scan_mod, _video = mv_scan_env

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr("app.services.scan_music_videos.subprocess.run", boom)
    stats = scan_mod.scan(db_session)
    assert stats.videos_upserted == 1 and stats.errors == 0
    assert _thumb_row(db_session) is None

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr("app.services.scan_music_videos.subprocess.run", missing)
    stats = scan_mod.scan(db_session)
    assert stats.errors == 0
    assert _thumb_row(db_session) is None
