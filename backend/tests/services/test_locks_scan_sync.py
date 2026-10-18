"""Lock-aware enrichment: locked fields are not overwritten by runner, folder scan,
or *arr sync."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.tv import Series
from app.services import metadata_locks, scan_library
from app.services.metadata import runner
from app.services.metadata._base import ProviderError
from app.services.sync import SyncStats, _upsert_movie


# ---------------------------------------------------------------------------
# TMDB client stub
# ---------------------------------------------------------------------------
class _FakeTMDB:
    """Stub TMDBClient that returns a fixed payload without network."""

    def __init__(self, payload: dict | None = None):
        self._payload = payload if payload is not None else {
            "title": "Remote Title",
            "overview": "Remote overview",
            "genres": [{"name": "Action"}, {"name": "Drama"}],
            "tagline": "Remote tagline",
            "vote_average": 8.0,
            "vote_count": 1000,
            "credits": {"cast": [], "crew": []},
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_movie(self, tmdb_id: int):
        return self._payload

    def get_series(self, tmdb_id: int):
        return self._payload

    def get_series_episodes(self, tmdb_id: int, season_number: int):
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _movie(db, *, tmdb_id=99, title="Local Title", genres=None, tagline="Local tag"):
    m = Movie(title=title, tmdb_id=tmdb_id, genres=genres or ["Horror"], tagline=tagline)
    db.add(m)
    db.commit()
    return m


def _artist(db, *, name="Local Artist", country="US"):
    a = Artist(name=name, country=country)
    db.add(a)
    db.commit()
    return a


# ---------------------------------------------------------------------------
# enrich_movie: locked fields are skipped
# ---------------------------------------------------------------------------
def test_enrich_movie_skips_locked_genres(db_session, monkeypatch):
    m = _movie(db_session, genres=["Horror"])
    metadata_locks.set_locks(db_session, "movie", m.id, ["genres"])

    monkeypatch.setattr(runner, "TMDBClient", lambda: _FakeTMDB())
    monkeypatch.setattr(runner, "tmdb_key", type("K", (), {"get": staticmethod(lambda: "key")})())
    result = runner.enrich_movie(db_session, m.id, force=True)

    assert result.status == "ok"
    db_session.refresh(m)
    # genres must be unchanged (locked).
    assert m.genres == ["Horror"]


def test_enrich_movie_skips_locked_tagline(db_session, monkeypatch):
    m = _movie(db_session, tagline="My Tagline")
    metadata_locks.set_locks(db_session, "movie", m.id, ["tagline"])

    monkeypatch.setattr(runner, "TMDBClient", lambda: _FakeTMDB())
    monkeypatch.setattr(runner, "tmdb_key", type("K", (), {"get": staticmethod(lambda: "key")})())
    result = runner.enrich_movie(db_session, m.id, force=True)

    assert result.status == "ok"
    db_session.refresh(m)
    assert m.tagline == "My Tagline"


def test_enrich_movie_writes_unlocked_fields(db_session, monkeypatch):
    m = _movie(db_session, genres=["Horror"], tagline="Old")
    # No locks set.

    monkeypatch.setattr(runner, "TMDBClient", lambda: _FakeTMDB())
    monkeypatch.setattr(runner, "tmdb_key", type("K", (), {"get": staticmethod(lambda: "key")})())
    result = runner.enrich_movie(db_session, m.id, force=True)

    assert result.status == "ok"
    db_session.refresh(m)
    # Both should be overwritten.
    assert "Action" in (m.genres or [])
    assert m.tagline == "Remote tagline"


def test_enrich_movie_partial_locks(db_session, monkeypatch):
    """Lock genres only; tagline should still update."""
    m = _movie(db_session, genres=["Horror"], tagline="Keep This")
    metadata_locks.set_locks(db_session, "movie", m.id, ["tagline"])

    monkeypatch.setattr(runner, "TMDBClient", lambda: _FakeTMDB())
    monkeypatch.setattr(runner, "tmdb_key", type("K", (), {"get": staticmethod(lambda: "key")})())
    runner.enrich_movie(db_session, m.id, force=True)

    db_session.refresh(m)
    # tagline is locked -> unchanged.
    assert m.tagline == "Keep This"
    # genres is not locked -> updated.
    assert "Action" in (m.genres or [])


# ---------------------------------------------------------------------------
# backfill_movie_genres: locked genres are skipped
# ---------------------------------------------------------------------------
def test_backfill_movie_genres_skips_locked(db_session, monkeypatch):
    m = _movie(db_session, genres=None, tmdb_id=42)
    m.genres = None
    m.metadata_synced_at = None
    db_session.commit()

    metadata_locks.set_locks(db_session, "movie", m.id, ["genres"])

    fake_payload = {
        "genres": [{"name": "Comedy"}],
        "credits": {"cast": [], "crew": []},
    }

    def _fake_get_movie(self, tmdb_id):
        return fake_payload

    monkeypatch.setattr(runner.TMDBClient, "get_movie", _fake_get_movie)
    monkeypatch.setattr(runner, "tmdb_key", type("K", (), {"get": staticmethod(lambda: "key")})())
    runner.backfill_movie_genres(db_session, pause_sec=0.0)

    db_session.refresh(m)
    assert m.genres is None  # locked, so not filled


def test_backfill_movie_genres_fills_unlocked(db_session, monkeypatch):
    m = _movie(db_session, genres=None, tmdb_id=43)
    m.genres = None
    m.metadata_synced_at = None
    db_session.commit()

    fake_payload = {"genres": [{"name": "Comedy"}], "credits": {"cast": [], "crew": []}}

    def _fake_get_movie(self, tmdb_id):
        return fake_payload

    monkeypatch.setattr(runner.TMDBClient, "get_movie", _fake_get_movie)
    monkeypatch.setattr(runner, "tmdb_key", type("K", (), {"get": staticmethod(lambda: "key")})())
    runner.backfill_movie_genres(db_session, pause_sec=0.0)

    db_session.refresh(m)
    assert m.genres == ["Comedy"]


# ---------------------------------------------------------------------------
# enrich_artist: locked fields are skipped
# ---------------------------------------------------------------------------

class _FakeMusicBrainz:
    def __init__(self, payload=None):
        self._payload = payload or {
            "name": "Remote Artist",
            "country": "GB",
            "begin-area": {"name": "London"},
            "life-span": {"begin": "1990", "end": None, "ended": False},
            "relations": [],
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_artist(self, mbid):
        return self._payload


class _FakeWikidata:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def enwiki_title(self, value):
        return None


class _FakeWikipedia:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_extract(self, title):
        return None


def _patch_artist_providers(monkeypatch):
    from app.services.metadata import wikidata
    monkeypatch.setattr(runner, "MusicBrainzClient", _FakeMusicBrainz)
    monkeypatch.setattr(runner, "WikipediaClient", _FakeWikipedia)
    monkeypatch.setattr(wikidata, "WikidataClient", _FakeWikidata)


def test_enrich_artist_skips_locked_country(db_session, monkeypatch):
    a = _artist(db_session, country="US")
    a.mbid = str(uuid.uuid4())
    db_session.commit()

    metadata_locks.set_locks(db_session, "artist", a.id, ["country"])
    _patch_artist_providers(monkeypatch)

    runner.enrich_artist(db_session, a.id, force=True)

    db_session.refresh(a)
    assert a.country == "US"  # locked -> not overwritten with "GB"


def test_enrich_artist_writes_unlocked_country(db_session, monkeypatch):
    a = _artist(db_session, country="US")
    a.mbid = str(uuid.uuid4())
    db_session.commit()

    _patch_artist_providers(monkeypatch)
    runner.enrich_artist(db_session, a.id, force=True)

    db_session.refresh(a)
    assert a.country == "GB"  # not locked -> updated


# ---------------------------------------------------------------------------
# Folder scan: locked track fields are skipped
# ---------------------------------------------------------------------------
def test_folder_scan_skips_locked_track_title(db_session, tmp_path, monkeypatch):
    """scan_music respects a locked track title and still updates unlocked fields."""
    # Create Artist -> Album -> Track in DB
    artist = Artist(name="Scan Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(title="Scan Album", artist_id=artist.id)
    db_session.add(album)
    db_session.flush()
    track = Track(title="Original Title", album_id=album.id, track_number=1, disc_number=1)
    db_session.add(track)
    db_session.flush()

    # A MediaFile already exists for this path so the scan hits the "else" branch.
    music_root = str(tmp_path / "music")
    os.makedirs(music_root, exist_ok=True)
    fake_path = str(tmp_path / "music" / "01.flac")
    now = datetime.now(timezone.utc)
    mf = MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=fake_path, scan_state=ScanState.ready,
        probed_at=now, size_bytes=100,
    )
    db_session.add(mf)
    db_session.commit()

    metadata_locks.set_locks(db_session, "track", track.id, ["title"])

    fake_ft = scan_library.FoundTrack(
        path=fake_path,
        artist="Scan Artist",
        album="Scan Album",
        title="Changed Title",
        track=2,
        disc=1,
        year=None,
        genre=None,
        artist_mbid=None,
        album_mbid=None,
        track_mbid=None,
        album_dir=music_root,
    )
    monkeypatch.setattr(scan_library, "discover_music", lambda root: [fake_ft])
    monkeypatch.setattr(scan_library.library_folders, "folders", lambda db, kind: [music_root])
    monkeypatch.setattr(scan_library.library_folders, "library_for_path", lambda db, path: None)

    scan_library.scan_music(db_session)

    db_session.refresh(track)
    assert track.title == "Original Title"  # locked -> unchanged
    assert track.track_number == 2           # not locked -> updated


# ---------------------------------------------------------------------------
# *arr sync: locked movie fields are skipped
# ---------------------------------------------------------------------------
def test_arr_sync_skips_locked_movie_title(db_session):
    """_upsert_movie respects a locked title and still updates unlocked fields."""
    movie = Movie(title="Original Title", tmdb_id=555, year=2000)
    db_session.add(movie)
    db_session.commit()

    metadata_locks.set_locks(db_session, "movie", movie.id, ["title"])

    payload = {
        "id": 0,               # radarr sentinel -> radarr_id = None
        "tmdbId": 555,
        "imdbId": None,
        "title": "Radarr Title",
        "year": 2024,
        "overview": "Some overview",
    }
    stats = SyncStats()
    _upsert_movie(db_session, payload, stats)

    db_session.refresh(movie)
    assert movie.title == "Original Title"  # locked -> unchanged
    assert movie.year == 2024               # not locked -> updated


def test_arr_sync_writes_unlocked_movie_title(db_session):
    """_upsert_movie writes title when it is not locked."""
    movie = Movie(title="Old Title", tmdb_id=556, year=2000)
    db_session.add(movie)
    db_session.commit()

    payload = {"id": 0, "tmdbId": 556, "imdbId": None, "title": "New Title", "year": 2024}
    stats = SyncStats()
    _upsert_movie(db_session, payload, stats)

    db_session.refresh(movie)
    assert movie.title == "New Title"  # not locked -> updated
