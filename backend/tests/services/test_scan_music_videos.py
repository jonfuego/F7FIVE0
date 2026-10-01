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
