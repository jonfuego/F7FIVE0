"""Movies Genre row (punch-list item 10, batch 7 item 9).

Cause: `enrich_movie` parsed tagline, cast, directors and rating from the TMDB
record but never `genres`, so a movie matched through TMDB (folder-scan
installs, Fix Match) kept `genres` null and the Movies page built a Genre row
of only "All". These tests cover the fix (genres saved on enrichment and
returned by the movies list) and the backfill for movies enriched earlier.
All TMDB traffic is faked; nothing touches the network.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.movie import Movie
from app.services import tmdb_key
from app.services.metadata import runner
from app.services.metadata._base import ProviderError


def _tmdb_record(tmdb_id: int, names: list[str]) -> dict:
    """The shape TMDB returns for /movie/{id}?append_to_response=credits."""
    return {
        "id": tmdb_id,
        "tagline": "A tagline.",
        "vote_average": 7.9,
        "vote_count": 1200,
        "genres": [{"id": 100 + i, "name": n} for i, n in enumerate(names)],
        "credits": {"cast": [], "crew": []},
    }


class _FakeTMDB:
    """Stand-in for TMDBClient. `records` maps tmdb id to a payload (None = 404,
    an exception instance = provider failure); `calls` records every lookup."""

    records: dict = {}
    calls: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_movie(self, tmdb_id):
        _FakeTMDB.calls.append(tmdb_id)
        rec = _FakeTMDB.records.get(tmdb_id)
        if isinstance(rec, Exception):
            raise rec
        return rec


def _fake_tmdb(monkeypatch, records: dict) -> None:
    _FakeTMDB.records = records
    _FakeTMDB.calls = []
    monkeypatch.setattr(tmdb_key, "get", lambda: "testkey")
    monkeypatch.setattr(runner, "TMDBClient", _FakeTMDB)


def _movie(db, title: str, tmdb_id: int, **kw) -> Movie:
    m = Movie(title=title, tmdb_id=tmdb_id, **kw)
    db.add(m)
    db.commit()
    return m


def _list_genres(client) -> dict:
    r = client.get("/api/movies?include_pending=true")
    assert r.status_code == 200, r.text
    return {row["title"]: row["genres"] for row in r.json()}


def test_tmdb_matched_movie_gets_genres_saved_and_listed(client, db_session, monkeypatch):
    _fake_tmdb(monkeypatch, {603: _tmdb_record(603, ["Action", "Science Fiction"])})
    movie = _movie(db_session, "The Matrix", 603)
    assert _list_genres(client) == {"The Matrix": None}

    result = runner.enrich_movie(db_session, movie.id)

    assert result.status == "ok"
    db_session.refresh(movie)
    assert movie.genres == ["Action", "Science Fiction"]
    assert _list_genres(client) == {"The Matrix": ["Action", "Science Fiction"]}


def test_enrich_with_no_tmdb_genres_keeps_existing(db_session, monkeypatch):
    _fake_tmdb(monkeypatch, {1: _tmdb_record(1, [])})
    movie = _movie(db_session, "Heat", 1, genres=["Crime"])
    runner.enrich_movie(db_session, movie.id, force=True)
    db_session.refresh(movie)
    assert movie.genres == ["Crime"]


def test_genre_names_ignore_blanks_and_repeats():
    payload = {"genres": [{"id": 1, "name": " Drama "}, {"id": 2, "name": ""},
                          {"id": 3, "name": "Drama"}, {"id": 4}, "Comedy", None]}
    assert runner.tmdb_genre_names(payload) == ["Drama", "Comedy"]
    assert runner.tmdb_genre_names(None) == []
    assert runner.tmdb_genre_names({"genres": None}) == []


def test_backfill_fills_existing_movie_and_second_run_changes_nothing(
    client, db_session, monkeypatch,
):
    _fake_tmdb(monkeypatch, {
        10: _tmdb_record(10, ["Drama"]),
        11: _tmdb_record(11, ["Comedy", "Romance"]),
        12: _tmdb_record(12, ["Horror"]),
    })
    # Already enriched earlier (fresh metadata_synced_at) but with no genres:
    # the case enrich_movie's TTL skip can never repair.
    now = datetime.now(timezone.utc)
    a = _movie(db_session, "Alpha", 10, metadata_synced_at=now, metadata_status="ok")
    b = _movie(db_session, "Bravo", 11, metadata_synced_at=now, metadata_status="ok", genres=[])
    # Has genres already (Radarr): must be left alone and never looked up.
    c = _movie(db_session, "Charlie", 12, genres=["Thriller"])
    # No TMDB id: nothing to look up.
    d = Movie(title="Delta")
    db_session.add(d)
    db_session.commit()

    assert runner.backfill_movie_genres(db_session, batch_size=1) == 2
    assert sorted(_FakeTMDB.calls) == [10, 11]
    assert _list_genres(client) == {
        "Alpha": ["Drama"],
        "Bravo": ["Comedy", "Romance"],
        "Charlie": ["Thriller"],
        "Delta": None,
    }
    for m in (a, b, c, d):
        db_session.refresh(m)
    assert a.metadata_synced_at is not None and a.metadata_status == "ok"

    snapshot = {m.title: (m.genres, m.metadata_synced_at, m.metadata_status, m.updated_at)
                for m in (a, b, c, d)}
    _FakeTMDB.calls = []
    assert runner.backfill_movie_genres(db_session, batch_size=1) == 0
    assert _FakeTMDB.calls == []
    for m in (a, b, c, d):
        db_session.refresh(m)
    assert {m.title: (m.genres, m.metadata_synced_at, m.metadata_status, m.updated_at)
            for m in (a, b, c, d)} == snapshot


def test_backfill_skips_failures_and_retries_next_run(db_session, monkeypatch):
    _fake_tmdb(monkeypatch, {
        20: ProviderError("tmdb returned 500"),
        21: None,
        22: _tmdb_record(22, ["Western"]),
    })
    _movie(db_session, "Down", 20)
    _movie(db_session, "Gone", 21)
    ok = _movie(db_session, "Fine", 22)

    assert runner.backfill_movie_genres(db_session) == 1
    db_session.refresh(ok)
    assert ok.genres == ["Western"]

    # The provider recovers: the failed movie is picked up on the next run.
    _FakeTMDB.records[20] = _tmdb_record(20, ["War"])
    assert runner.backfill_movie_genres(db_session) == 1


def test_backfill_does_nothing_without_a_tmdb_key(db_session, monkeypatch):
    _fake_tmdb(monkeypatch, {30: _tmdb_record(30, ["Drama"])})
    monkeypatch.setattr(tmdb_key, "get", lambda: "")
    _movie(db_session, "Quiet", 30)
    assert runner.backfill_movie_genres(db_session) == 0
    assert _FakeTMDB.calls == []
