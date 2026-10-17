"""*arr sync progress (Admin > Scans): the status carries a real count, and the
sync saves in batches, so rows show up while it runs and a failure keeps what
was done.

Fixtures and helpers come from test_library_scan.py, like test_admin_scans.py.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app import scheduler
from app.config import settings
from app.models.media_file import MediaFile
from app.models.movie import Movie
from app.services import arr_settings, scan_status, sync
from tests.test_library_scan import (  # noqa: F401  (fixtures are used by name)
    _count, _fake_probe, _touch, file_db, libs,
)


@pytest.fixture(autouse=True)
def _clean_arr_cache():
    arr_settings.reset_cache()
    yield
    arr_settings.reset_cache()


def _radarr_key(monkeypatch):
    # Set after the libs fixture, which blanks every *arr key.
    monkeypatch.setattr(settings, 'radarr_api_key', 'abc')
    arr_settings.reset_cache()


class FakeRadarr:
    movies: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_movies(self):
        return list(self.movies)


def _movies(root, n, *, start=1):
    out = []
    for i in range(start, start + n):
        path = root / f"Movie {i:03d} (2000)" / f"Movie {i:03d} (2000).mkv"
        _touch(path)
        out.append({
            "id": i, "tmdbId": 1000 + i, "title": f"Movie {i:03d}", "year": 2000,
            "hasFile": True, "movieFile": {"path": str(path), "size": 16},
        })
    return out


@pytest.fixture()
def radarr60(monkeypatch, libs):
    _radarr_key(monkeypatch)
    FakeRadarr.movies = _movies(libs["movies"], 60)
    monkeypatch.setattr(sync, "RadarrClient", FakeRadarr)
    monkeypatch.setattr(sync, "schedule_pending_enrichment", lambda stats: None)
    _fake_probe(monkeypatch)
    return FakeRadarr.movies


def _radarr(factory) -> dict:
    with factory() as db:
        return scan_status.arr_read(db)["apps"].get("radarr", {})


def test_the_status_carries_done_total_and_counts_while_the_app_runs(file_db, radarr60, monkeypatch):
    """B1.1: a 60-movie Radarr shows at least two writes with a rising `done`."""
    seen = []
    real = scheduler._arr_status

    def spy(fn, *args, **kwargs):
        real(fn, *args, **kwargs)
        entry = _radarr(file_db)
        if entry.get("state") == "running":
            seen.append(dict(entry))

    monkeypatch.setattr(scheduler, "_arr_status", spy)
    scheduler._run_full_sync(["radarr"])

    mid = [e for e in seen if 0 < e.get("done", 0) < 60]
    assert len(mid) >= 2
    dones = [e["done"] for e in mid]
    assert dones == sorted(set(dones)) and len(dones) >= 2
    for e in mid:
        assert e["total"] == 60
        for key in ("ready", "missing", "errors", "refused"):
            assert key in e
    final = _radarr(file_db)
    assert final["state"] == "done" and final["done"] == 60 and final["total"] == 60
    assert final["synced"] == 60 and final["ready"] == 60
    assert final["missing"] == 0 and final["refused"] == 0 and final["errors"] == 0


def test_rows_are_visible_to_other_sessions_while_the_sync_runs(file_db, radarr60, monkeypatch):
    """B1 expected: movies appear in the library during the run."""
    counts = []
    real = scheduler._arr_status

    def spy(fn, *args, **kwargs):
        real(fn, *args, **kwargs)
        counts.append(_count(file_db, Movie))

    monkeypatch.setattr(scheduler, "_arr_status", spy)
    scheduler._run_full_sync(["radarr"])
    during = [c for c in counts if c < 60]
    assert max(during) >= sync.BATCH_SIZE
    assert _count(file_db, Movie) == 60


def test_a_failure_partway_keeps_the_committed_batch_and_says_how_far_it_got(file_db, radarr60, monkeypatch):
    """B1.2: raise after item 30 of 60. The first batch is saved; the open one is not."""
    def boom(n):
        if n == 31:
            raise RuntimeError("the NAS went away")

    _fake_probe(monkeypatch, hook=boom)
    enriched = []
    monkeypatch.setattr(sync, "schedule_pending_enrichment", lambda stats: enriched.append(list(stats.pending_movies)))

    scheduler._run_full_sync(["radarr"])

    assert sync.BATCH_SIZE <= 50
    assert _count(file_db, Movie) == sync.BATCH_SIZE
    assert _count(file_db, MediaFile) == sync.BATCH_SIZE
    entry = _radarr(file_db)
    assert entry["state"] in ("failed", "interrupted")
    assert entry["done"] == sync.BATCH_SIZE and entry["total"] == 60
    with file_db() as db:
        status = scan_status.arr_read(db)
    assert status["state"] == "idle" and "the NAS went away" in (status["last_error"] or "")
    # Enrichment is only queued for rows that are in the database.
    with file_db() as db:
        saved = set(db.scalars(select(Movie.id)).all())
    assert enriched and set(enriched[0]) <= saved


def test_missing_and_refused_files_are_counted(file_db, libs, monkeypatch, tmp_path):
    _radarr_key(monkeypatch)
    # The test config allows the whole temp dir; hold the sync to the library roots.
    monkeypatch.setattr(settings, "stream_unsafe_allow_any_path", False)
    monkeypatch.setattr(settings, "stream_allowed_roots", "")
    movies = _movies(libs["movies"], 3)
    gone = _movies(libs["movies"], 1, start=4)
    (libs["movies"] / "Movie 004 (2000)" / "Movie 004 (2000).mkv").unlink()
    outside = tmp_path / "elsewhere"
    stray = _movies(outside, 1, start=5)
    FakeRadarr.movies = movies + gone + stray
    monkeypatch.setattr(sync, "RadarrClient", FakeRadarr)
    monkeypatch.setattr(sync, "schedule_pending_enrichment", lambda stats: None)
    _fake_probe(monkeypatch)

    scheduler._run_full_sync(["radarr"])

    entry = _radarr(file_db)
    assert entry["total"] == 5 and entry["done"] == 5
    assert entry["ready"] == 3 and entry["missing"] == 1 and entry["refused"] == 1
    with file_db() as db:
        assert db.scalar(select(func.count()).select_from(Movie)) == 5
