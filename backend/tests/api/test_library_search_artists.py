"""GET /api/search: artist rows are opt-in via include_artists (item 10)."""
from __future__ import annotations

import uuid

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, Track


def _artist_with_album(db, artist_name: str, album_title: str, *, ready: bool = True):
    artist = Artist(name=artist_name)
    db.add(artist)
    db.flush()
    album = Album(artist_id=artist.id, title=album_title)
    db.add(album)
    db.flush()
    track = Track(album_id=album.id, title="Track", track_number=1)
    db.add(track)
    db.flush()
    db.add(MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=f"//nas/music/{uuid.uuid4()}.flac",
        scan_state=ScanState.ready if ready else ScanState.pending,
        duration_sec=200,
    ))
    db.commit()
    return artist, album


def test_search_returns_artist_match_when_included(client, db_session):
    artist, album = _artist_with_album(
        db_session, "The Birthday Party", "Junkyard",
    )
    r = client.get(
        "/api/search", params={"q": "Birthday party", "include_artists": "true"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert [(x["kind"], x["id"]) for x in rows] == [
        ("artist", str(artist.id)),
        ("album", str(album.id)),
    ]
    assert rows[0]["title"] == "The Birthday Party"


def test_search_omits_artists_by_default_for_older_clients(client, db_session):
    _artist_with_album(db_session, "The Birthday Party", "Junkyard")
    r = client.get("/api/search", params={"q": "Birthday party"})
    assert r.status_code == 200
    assert {x["kind"] for x in r.json()} == {"album"}


def test_search_artist_needs_a_ready_track(client, db_session):
    _artist_with_album(db_session, "Pending Band", "Demo", ready=False)
    r = client.get(
        "/api/search", params={"q": "pending", "include_artists": "true"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_search_artist_terms_must_all_match_the_name(client, db_session):
    _artist_with_album(db_session, "The Birthday Party", "Junkyard")
    r = client.get(
        "/api/search",
        params={"q": "birthday junkyard", "include_artists": "true"},
    )
    kinds = [x["kind"] for x in r.json()]
    # "junkyard" is the album title, not the artist name: album only.
    assert kinds == ["album"]
