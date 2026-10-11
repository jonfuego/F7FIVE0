"""Fields behind the Home hero facts line (batch 7 item 5).

The hero reads the detail call of the featured item. Movies already carried
runtime, genres and rating; albums did not carry their genres, so the facts
line had nothing to show for them. These tests lock in the album `genres`
field and the movie and series fields the line depends on.
"""
from __future__ import annotations

from app.models.movie import Movie
from app.models.music import Album, Artist, Track
from app.models.tv import Episode, Series


def test_album_detail_returns_genres_and_track_durations(client, db_session):
    artist = Artist(name="Facts Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(artist_id=artist.id, title="Facts Album", genres=["Rock", "Blues"])
    db_session.add(album)
    db_session.flush()
    for n, secs in enumerate((180, 240), start=1):
        db_session.add(Track(
            album_id=album.id, title=f"T{n}", track_number=n, duration_sec=secs,
        ))
    db_session.commit()

    r = client.get(f"/api/albums/{album.id}?include_pending=true")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["genres"] == ["Rock", "Blues"]
    assert [t["duration_sec"] for t in body["tracks"]] == [180, 240]


def test_album_detail_without_genres_returns_empty_list(client, db_session):
    artist = Artist(name="Plain Artist")
    db_session.add(artist)
    db_session.flush()
    album = Album(artist_id=artist.id, title="Plain Album")
    db_session.add(album)
    db_session.commit()

    r = client.get(f"/api/albums/{album.id}?include_pending=true")

    assert r.status_code == 200, r.text
    assert r.json()["genres"] == []


def test_movie_detail_carries_runtime_genres_and_rating(client, db_session):
    m = Movie(
        title="Facts Movie", runtime_min=108, genres=["Action"], tmdb_rating=7.9,
    )
    db_session.add(m)
    db_session.commit()

    r = client.get(f"/api/movies/{m.id}?include_pending=true")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runtime_min"] == 108
    assert body["genres"] == ["Action"]
    assert body["tmdb_rating"] == 7.9


def test_series_detail_carries_episode_season_numbers(client, db_session):
    s = Series(title="Facts Series")
    db_session.add(s)
    db_session.flush()
    for season, ep in ((1, 1), (1, 2), (2, 1)):
        db_session.add(Episode(
            series_id=s.id, season_number=season, episode_number=ep,
        ))
    db_session.commit()

    r = client.get(f"/api/series/{s.id}?include_pending=true")

    assert r.status_code == 200, r.text
    eps = r.json()["episodes"]
    assert sorted({e["season_number"] for e in eps}) == [1, 2]
    assert len(eps) == 3
