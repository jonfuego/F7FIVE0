"""A music videos folder named a little differently from the music library
artist ("Birthday Party" vs "The Birthday Party") used to become a second
artist. Fix Match on it then failed with a bare "another record already uses
that match", and Merge (albums and tracks only) deleted its videos through the
cascade. Three fixes, one test group each:

1. The 409 names the artist that holds the MusicBrainz id and where it shows.
2. Merge moves music video releases and videos, and undo moves them back.
3. The music videos scan files a new folder under an existing artist with the
   same folded name, or under a merge alias, instead of making a duplicate.
"""
from __future__ import annotations

import pytest

from app.models.music import Album, Artist, ArtistAlias, MusicVideo, MusicVideoRelease
from app.services import artist_merge
from app.services.scan_music_videos import ScanStats, _upsert_artist

MBID = "ec3b23be-4a2c-4db8-9e20-5f1d1e5e8e9a"


def _artist(db, name, mbid=None):
    a = Artist(name=name, mbid=mbid)
    db.add(a)
    db.flush()
    return a


def _videos(db, artist, folder="Mutiny", count=2):
    release = MusicVideoRelease(artist_id=artist.id, title=folder, source_subpath=folder)
    db.add(release)
    db.flush()
    for i in range(count):
        db.add(MusicVideo(artist_id=artist.id, release_id=release.id, title=f"Video {i}"))
    db.flush()
    return release


# ---------------------------------------------------------------------------
# 1. The 409 names the holder
# ---------------------------------------------------------------------------
def test_already_matched_names_the_artist_and_where(client, db_session):
    library = _artist(db_session, "The Birthday Party", mbid=MBID)
    db_session.add(Album(artist_id=library.id, title="Junkyard"))
    folder = _artist(db_session, "Birthday Party")
    _videos(db_session, folder)
    db_session.commit()

    r = client.post(
        f"/api/admin/match/artist/{folder.id}",
        json={"source": "musicbrainz", "ref": MBID},
    )

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail.startswith("already_matched")
    assert "The Birthday Party (music library)" in detail
    assert "Merge" in detail
    db_session.refresh(folder)
    assert folder.mbid is None


# ---------------------------------------------------------------------------
# 2. Merge moves music videos; undo moves them back
# ---------------------------------------------------------------------------
def test_merge_moves_music_videos_and_undo_returns_them(db_session):
    target = _artist(db_session, "The Birthday Party", mbid=MBID)
    source = _artist(db_session, "Birthday Party")
    release = _videos(db_session, source, count=3)
    db_session.commit()

    assert artist_merge.preview(db_session, source)["music_videos"] == 3
    record = artist_merge.merge(db_session, source, target)
    db_session.commit()

    db_session.expire_all()
    assert db_session.get(MusicVideoRelease, release.id).artist_id == target.id
    videos = db_session.query(MusicVideo).filter(MusicVideo.release_id == release.id).all()
    assert len(videos) == 3
    assert all(v.artist_id == target.id for v in videos)

    restored = artist_merge.undo(db_session, record)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(MusicVideoRelease, release.id).artist_id == restored.id
    videos = db_session.query(MusicVideo).filter(MusicVideo.release_id == release.id).all()
    assert len(videos) == 3
    assert all(v.artist_id == restored.id for v in videos)


def test_merge_with_loaded_collections_does_not_delete_videos(db_session):
    # Artist.music_videos / music_video_releases are delete-orphan; a list
    # loaded before the merge must not take the moved rows with the source.
    target = _artist(db_session, "The Birthday Party")
    source = _artist(db_session, "Birthday Party")
    _videos(db_session, source)
    db_session.commit()
    assert len(source.music_videos) == 2
    assert len(source.music_video_releases) == 1

    artist_merge.merge(db_session, source, target)
    db_session.commit()

    assert db_session.query(MusicVideo).count() == 2
    assert db_session.query(MusicVideoRelease).count() == 1


def test_merge_stops_on_a_release_folder_both_artists_have(db_session):
    target = _artist(db_session, "The Birthday Party")
    source = _artist(db_session, "Birthday Party")
    _videos(db_session, target, folder="Mutiny")
    _videos(db_session, source, folder="Mutiny")
    db_session.commit()

    with pytest.raises(artist_merge.MergeError):
        artist_merge.merge(db_session, source, target)
    db_session.rollback()

    assert db_session.get(Artist, source.id) is not None
    assert db_session.query(MusicVideo).count() == 4


# ---------------------------------------------------------------------------
# 3. The music videos scan reuses an existing artist
# ---------------------------------------------------------------------------
def test_scan_files_a_folder_under_the_same_folded_name(db_session):
    library = _artist(db_session, "The Birthday Party", mbid=MBID)
    stats = ScanStats()

    got = _upsert_artist(db_session, "Birthday Party", stats)

    assert got.id == library.id
    assert stats.artists_upserted == 0
    assert db_session.query(Artist).count() == 1


def test_scan_exact_name_wins(db_session):
    exact = _artist(db_session, "Birthday Party")
    _artist(db_session, "The Birthday Party")

    assert _upsert_artist(db_session, "birthday party", ScanStats()).id == exact.id


def test_scan_ambiguous_folded_name_makes_a_new_artist(db_session):
    _artist(db_session, "The Birthday Party")
    _artist(db_session, "Birthday-Party")
    stats = ScanStats()

    got = _upsert_artist(db_session, "Birthday  Party!", stats)

    assert got.name == "Birthday  Party!"
    assert stats.artists_upserted == 1


def test_scan_follows_a_merge_alias(db_session):
    target = _artist(db_session, "The Birthday Party")
    db_session.add(ArtistAlias(
        target_artist_id=target.id, name_key="nick cave's first band",
        source_name="Nick Cave's First Band",
    ))
    db_session.flush()

    assert _upsert_artist(db_session, "Nick Cave's First Band", ScanStats()).id == target.id


def test_scan_new_name_still_makes_an_artist(db_session):
    _artist(db_session, "The Birthday Party")
    stats = ScanStats()

    got = _upsert_artist(db_session, "Crime and the City Solution", stats)

    assert got.name == "Crime and the City Solution"
    assert stats.artists_upserted == 1
