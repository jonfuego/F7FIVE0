"""The artist bio excerpt on the album detail the Home hero reads.

When the featured pick is an album, the hero shows the first few whole
sentences of the artist's bio (services/bio_excerpt). The album detail carries it as `artist_bio_excerpt`, null
when the artist has no bio.
"""
from __future__ import annotations

from app.models.music import Album, Artist

BIO = (
    "Radiohead are a band. "
    "Radiohead are an English rock band formed in Abingdon, Oxfordshire, in "
    "1985. The members are Thom Yorke, brothers Jonny Greenwood and Colin "
    "Greenwood, Ed O'Brien and Philip Selway. They have worked with the "
    "producer Nigel Godrich since 1994. Their first single was Creep, "
    "released in 1992."
)


def _album(db, artist):
    db.add(artist)
    db.flush()
    album = Album(artist_id=artist.id, title="Bio Album")
    db.add(album)
    db.commit()
    return album


def test_album_detail_carries_an_artist_bio_excerpt_of_whole_sentences(client, db_session):
    album = _album(db_session, Artist(name="Radiohead", bio_text=BIO, bio_source="wikipedia"))

    r = client.get(f"/api/albums/{album.id}?include_pending=true")

    assert r.status_code == 200, r.text
    excerpt = r.json()["artist_bio_excerpt"]
    # Four whole sentences at most, so the fifth (Creep) is left out and the
    # text ends on a sentence, not an ellipsis.
    assert excerpt.startswith("Radiohead are a band.")
    assert excerpt.endswith("Nigel Godrich since 1994.")
    assert len(excerpt) <= 480
    assert "Creep" not in excerpt
    assert "\u2026" not in excerpt


def test_album_detail_has_no_excerpt_when_the_artist_has_no_bio(client, db_session):
    album = _album(db_session, Artist(name="No Bio"))

    r = client.get(f"/api/albums/{album.id}?include_pending=true")

    assert r.status_code == 200, r.text
    assert r.json()["artist_bio_excerpt"] is None


def test_album_detail_has_no_excerpt_for_a_blank_bio(client, db_session):
    album = _album(db_session, Artist(name="Blank Bio", bio_text="   "))

    r = client.get(f"/api/albums/{album.id}?include_pending=true")

    assert r.json()["artist_bio_excerpt"] is None
