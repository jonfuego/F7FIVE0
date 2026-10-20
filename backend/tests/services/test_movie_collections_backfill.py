"""Unit tests for the collections backfill in services/metadata/runner.py."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.movie import Movie


def _movie(db, *, tmdb_id=None, coll_id=None, coll_name=None, checked_at=None) -> Movie:
    m = Movie(
        title="Film",
        tmdb_id=tmdb_id,
        tmdb_collection_id=coll_id,
        tmdb_collection_name=coll_name,
        tmdb_collection_checked_at=checked_at,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# backfill_movie_collections
# ---------------------------------------------------------------------------

def test_backfill_skips_when_no_tmdb_key(db_session):
    from app.services.metadata import runner

    _movie(db_session, tmdb_id=1)
    db_session.commit()

    with patch("app.services.metadata.runner.tmdb_key") as mock_key:
        mock_key.get.return_value = None
        filled = runner.backfill_movie_collections(db_session, batch_size=25, pause_sec=0)

    assert filled == 0


def test_backfill_skips_already_checked(db_session):
    from app.services.metadata import runner

    _movie(db_session, tmdb_id=100, checked_at=datetime.now(timezone.utc))
    db_session.commit()

    with patch("app.services.metadata.runner.tmdb_key") as mock_key, \
         patch("app.services.metadata.runner.TMDBClient") as MockClient:
        mock_key.get.return_value = "fake_key"
        filled = runner.backfill_movie_collections(db_session, batch_size=25, pause_sec=0)

    assert filled == 0
    # The TMDBClient should not have been used to fetch anything.
    assert MockClient.return_value.__enter__.return_value.get_movie.call_count == 0


def test_backfill_skips_movies_without_tmdb_id(db_session):
    from app.services.metadata import runner

    _movie(db_session, tmdb_id=None)
    db_session.commit()

    with patch("app.services.metadata.runner.tmdb_key") as mock_key, \
         patch("app.services.metadata.runner.TMDBClient") as MockClient:
        mock_key.get.return_value = "fake_key"
        instance = MockClient.return_value.__enter__.return_value
        instance.get_movie.return_value = {}
        filled = runner.backfill_movie_collections(db_session, batch_size=25, pause_sec=0)

    assert filled == 0
    assert instance.get_movie.call_count == 0


def test_backfill_fills_collection_from_tmdb(db_session):
    from app.services.metadata import runner

    m = _movie(db_session, tmdb_id=27205)
    db_session.commit()

    with patch("app.services.metadata.runner.tmdb_key") as mock_key, \
         patch("app.services.metadata.runner.TMDBClient") as MockClient:
        mock_key.get.return_value = "fake_key"
        instance = MockClient.return_value.__enter__.return_value
        instance.get_movie.return_value = {
            "id": 27205,
            "title": "Inception",
            "belongs_to_collection": {
                "id": 86311,
                "name": "The Inception Collection",
            },
        }
        filled = runner.backfill_movie_collections(db_session, batch_size=25, pause_sec=0)

    assert filled == 1
    db_session.expire(m)
    reloaded = db_session.get(Movie, m.id)
    assert reloaded.tmdb_collection_checked_at is not None
    assert reloaded.tmdb_collection_id == 86311
    assert reloaded.tmdb_collection_name == "The Inception Collection"


def test_backfill_marks_checked_at_on_no_collection(db_session):
    from app.services.metadata import runner

    m = _movie(db_session, tmdb_id=12345)
    db_session.commit()

    with patch("app.services.metadata.runner.tmdb_key") as mock_key, \
         patch("app.services.metadata.runner.TMDBClient") as MockClient:
        mock_key.get.return_value = "fake_key"
        instance = MockClient.return_value.__enter__.return_value
        instance.get_movie.return_value = {
            "id": 12345,
            "title": "Standalone",
            "belongs_to_collection": None,
        }
        runner.backfill_movie_collections(db_session, batch_size=25, pause_sec=0)

    db_session.expire(m)
    reloaded = db_session.get(Movie, m.id)
    assert reloaded.tmdb_collection_checked_at is not None
    assert reloaded.tmdb_collection_id is None
