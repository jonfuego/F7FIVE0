"""The artist detail call carries each album's type and secondary types.

The artist page groups its Discography into Albums, EPs, Singles and Other
from `album_type` and `secondary_types`, so both fields must be on every
album in `GET /api/artists/{id}` (and on the plain album list).
"""
from __future__ import annotations

from datetime import date

from app.models.music import Album, Artist


def _artist_with_albums(db_session):
    artist = Artist(name="Disco Artist")
    db_session.add(artist)
    db_session.flush()
    typed = Album(
        artist_id=artist.id, title="Live At Home", release_date=date(2001, 5, 1),
        album_type="Album", secondary_types=["Live", "Compilation"],
    )
    plain = Album(
        artist_id=artist.id, title="Studio", release_date=date(1999, 1, 1),
        album_type="EP",
    )
    untyped = Album(artist_id=artist.id, title="Mystery")
    db_session.add_all([typed, plain, untyped])
    db_session.commit()
    return artist


def test_artist_detail_albums_carry_type_and_secondary_types(client, db_session):
    artist = _artist_with_albums(db_session)

    r = client.get(f"/api/artists/{artist.id}?include_pending=true")

    assert r.status_code == 200, r.text
    by_title = {a["title"]: a for a in r.json()["albums"]}
    assert by_title["Live At Home"]["album_type"] == "Album"
    assert by_title["Live At Home"]["secondary_types"] == ["Live", "Compilation"]
    assert by_title["Studio"]["album_type"] == "EP"
    assert by_title["Studio"]["secondary_types"] == []
    assert by_title["Mystery"]["album_type"] is None
    assert by_title["Mystery"]["secondary_types"] == []


def test_album_list_carries_secondary_types(client, db_session):
    artist = _artist_with_albums(db_session)

    r = client.get(f"/api/albums?artist_id={artist.id}&include_pending=true")

    assert r.status_code == 200, r.text
    by_title = {a["title"]: a for a in r.json()}
    assert by_title["Live At Home"]["secondary_types"] == ["Live", "Compilation"]
    assert by_title["Mystery"]["secondary_types"] == []


def test_album_detail_still_carries_secondary_types(client, db_session):
    artist = _artist_with_albums(db_session)
    album = db_session.query(Album).filter_by(title="Live At Home").one()

    r = client.get(f"/api/albums/{album.id}?include_pending=true")

    assert r.status_code == 200, r.text
    assert r.json()["secondary_types"] == ["Live", "Compilation"]
    assert artist.id == album.artist_id
