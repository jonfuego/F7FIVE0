"""Folder scanner (no-*arr path) for movies, TV, and music."""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.art import ArtOverride
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.tv import Episode, Series
from app.services import ffprobe, scan_library
from app.services.scan_library import (
    parse_episode, parse_season_dir, parse_title_year, parse_tmdb_tag,
    parse_track_filename,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,title,year", [
    ("The Matrix (1999)", "The Matrix", 1999),
    ("The Matrix (1999) [1080p] {tmdb-603}", "The Matrix", 1999),
    ("The.Matrix.1999.1080p.BluRay.x264", "The Matrix", 1999),
    ("Blade Runner 2049 (2017)", "Blade Runner 2049", 2017),
    ("1917 (2019)", "1917", 2019),
    ("Heat", "Heat", None),
    ("Alien.1080p.BluRay", "Alien", None),
])
def test_parse_title_year(name, title, year):
    assert parse_title_year(name) == (title, year)


def test_parse_tmdb_tag():
    assert parse_tmdb_tag("Heat (1995) {tmdb-949}") == 949
    assert parse_tmdb_tag("Heat (1995) [tmdbid=949]") == 949
    assert parse_tmdb_tag("Heat (1995)") is None


@pytest.mark.parametrize("fname,expected", [
    ("Show - S01E02 - Pilot Part 2.mkv", (1, 2, "Pilot Part 2")),
    ("show.s03e10.720p.hdtv.mkv", (3, 10, None)),
    ("Show - S01E01E02 - Double.mkv", (1, 1, "Double")),
    ("Show 2x05 Title.mp4", (2, 5, "Title")),
    ("Show - Behind the scenes.mkv", None),
])
def test_parse_episode(fname, expected):
    assert parse_episode(fname) == expected


@pytest.mark.parametrize("name,expected", [
    ("Season 01", 1), ("season 3", 3), ("Specials", 0), ("Extras", None), ("S01", None),
])
def test_parse_season_dir(name, expected):
    assert parse_season_dir(name) == expected


@pytest.mark.parametrize("fname,expected", [
    ("01 - Intro.flac", (None, 1, "Intro")),
    ("2-05 Song.mp3", (2, 5, "Song")),
    ("07. Another.m4a", (None, 7, "Another")),
    ("No Number.mp3", (None, None, "No Number")),
])
def test_parse_track_filename(fname, expected):
    assert parse_track_filename(fname) == expected


# ---------------------------------------------------------------------------
# DB scans against a temp library
# ---------------------------------------------------------------------------
def _touch(path: Path, size: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def _png(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 100, 20)).save(buf, "PNG")
    path.write_bytes(buf.getvalue())


@pytest.fixture()
def fake_probe(monkeypatch):
    calls: list[str] = []

    def _probe(path, timeout=30.0):
        calls.append(path)
        if not os.path.exists(path):
            return None
        return ffprobe.ProbeResult(
            container=os.path.splitext(path)[1].lstrip("."), size_bytes=os.path.getsize(path),
            duration_sec=120, bitrate_kbps=1000, video_codec="h264", audio_codec="aac",
            audio_channels=2, width=1920, height=1080,
        )
    monkeypatch.setattr(ffprobe, "probe", _probe)
    # Enrichment is scheduled on a real scheduler in prod; no-op here.
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_movie", lambda *_a, **_k: None)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_artist", lambda *_a, **_k: None)
    monkeypatch.setattr(scan_library.scheduler, "schedule_enrich_album", lambda *_a, **_k: None)
    return calls


@pytest.fixture()
def system_user(db_session):
    from app.models.user import User
    from app.services.art import SYSTEM_USER_ID
    db_session.add(User(id=SYSTEM_USER_ID, username="system", display_name="System",
                        password_hash="!", role="admin", is_active=False))
    db_session.flush()


@pytest.fixture()
def libs(tmp_path, monkeypatch):
    for key in ("radarr_api_key", "sonarr_api_key", "lidarr_api_key", "tmdb_api_key"):
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "path_rewrite_rules", "")
    monkeypatch.setattr(settings, "art_root", tmp_path / "art")
    roots = {k: tmp_path / k for k in ("movies", "tv", "music")}
    for k, p in roots.items():
        p.mkdir()
        monkeypatch.setattr(settings, f"library_root_{k}", str(p))
    return roots


def test_enabled_flags_follow_arr_keys(libs, monkeypatch):
    assert scan_library.movies_enabled()
    monkeypatch.setattr(settings, "radarr_api_key", "abc")
    assert not scan_library.movies_enabled()
    monkeypatch.setattr(settings, "library_root_tv", "")
    assert not scan_library.tv_enabled()


def test_scan_movies(db_session, libs, fake_probe, system_user):
    root = libs["movies"]
    _touch(root / "Heat (1995)" / "Heat (1995).mkv", 100)
    _touch(root / "Heat (1995)" / "Heat (1995)-sample.mkv", 5)
    _touch(root / "Heat (1995)" / "Extras" / "Making of.mkv")
    _png(root / "Heat (1995)" / "poster.png")
    _touch(root / "Alien.1979.1080p.BluRay.mkv")

    stats = scan_library.scan_movies(db_session)
    movies = {m.title: m for m in db_session.scalars(select(Movie)).all()}
    assert set(movies) == {"Heat", "Alien"}
    assert movies["Heat"].year == 1995 and movies["Alien"].year == 1979
    assert stats.movies == 2 and stats.files_probed == 2
    art = db_session.get(ArtOverride, ("movie", movies["Heat"].id, "poster"))
    assert art is not None and art.source_kind == "local"

    # Rescan: nothing new, nothing re-probed.
    fake_probe.clear()
    stats = scan_library.scan_movies(db_session)
    assert stats.movies == 0 and fake_probe == []
    assert db_session.scalar(select(MediaFile).where(MediaFile.kind == MediaKind.movie).limit(1)) is not None

    # File disappears -> missing, row kept.
    os.remove(root / "Alien.1979.1080p.BluRay.mkv")
    scan_library.scan_movies(db_session)
    mf = db_session.scalar(select(MediaFile).where(MediaFile.ref_id == movies["Alien"].id))
    assert mf.scan_state == ScanState.missing


def test_scan_movies_never_overwrites_admin_art(db_session, libs, fake_probe, system_user):
    root = libs["movies"]
    _touch(root / "Heat (1995)" / "Heat (1995).mkv")
    scan_library.scan_movies(db_session)
    movie = db_session.scalar(select(Movie))
    from app.services.art import SYSTEM_USER_ID
    db_session.add(ArtOverride(entity_kind="movie", entity_id=movie.id, role="poster",
                               local_path="x.png", source_kind="upload", set_by=SYSTEM_USER_ID))
    db_session.flush()
    _png(root / "Heat (1995)" / "poster.png")
    scan_library.scan_movies(db_session)
    assert db_session.get(ArtOverride, ("movie", movie.id, "poster")).source_kind == "upload"


def test_scan_tv(db_session, libs, fake_probe, system_user):
    show = libs["tv"] / "Some Show (2020)"
    _touch(show / "Season 01" / "Some Show - S01E01 - Pilot.mkv")
    _touch(show / "Season 01" / "Some Show - S01E02 - Second.mkv")
    _touch(show / "Specials" / "Some Show - S00E01 - Special.mkv")
    _png(show / "poster.jpg".replace(".jpg", ".png"))

    stats = scan_library.scan_tv(db_session)
    series = db_session.scalar(select(Series))
    assert series.title == "Some Show"
    eps = db_session.scalars(select(Episode).order_by(Episode.season_number, Episode.episode_number)).all()
    assert [(e.season_number, e.episode_number, e.title) for e in eps] == [
        (0, 1, "Special"), (1, 1, "Pilot"), (1, 2, "Second"),
    ]
    assert stats.series == 1 and stats.episodes == 3
    assert db_session.get(ArtOverride, ("series", series.id, "poster")) is not None
    # Rescan keeps one series.
    scan_library.scan_tv(db_session)
    assert len(db_session.scalars(select(Series)).all()) == 1


def test_scan_music_folder_names(db_session, libs, fake_probe, system_user):
    album_dir = libs["music"] / "Some Artist" / "Great Album (2001)"
    _touch(album_dir / "01 - Opener.flac")
    _touch(album_dir / "02 - Closer.flac")
    _touch(libs["music"] / "Some Artist" / "Double (1999)" / "CD2" / "01 - Disc Two.mp3")
    _png(album_dir / "cover.png")

    scan_library.scan_music(db_session)
    artist = db_session.scalar(select(Artist))
    assert artist.name == "Some Artist"
    albums = {a.title: a for a in db_session.scalars(select(Album)).all()}
    assert set(albums) == {"Great Album", "Double"}
    assert albums["Great Album"].release_date.year == 2001
    tracks = {t.title: t for t in db_session.scalars(select(Track)).all()}
    assert tracks["Opener"].track_number == 1 and tracks["Closer"].track_number == 2
    assert tracks["Disc Two"].disc_number == 2
    assert tracks["Opener"].duration_sec == 120
    assert db_session.get(ArtOverride, ("album", albums["Great Album"].id, "cover")) is not None
