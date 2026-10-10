"""Merge artists: durable alias, undo, and scan-time feat-credit attach.

Covers the three cases the punch-list calls out (ui-review item 2, criterion 12):
  - merge then rescan does NOT recreate the source artist (the alias resolves
    it to the target).
  - undo restores the source artist with its albums and tracks.
  - a "feat." credit attaches to the main artist (and keeps the credit text)
    while an "&" credit does NOT split.

Tests run against the shared in-memory SQLite db_session fixture, and the
file-backed `file_db` / `libs` fixtures for the full folder-scan paths (reused
from test_library_scan.py). Models are created via metadata create_all.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.music import (
    Album, Artist, ArtistAlias, ArtistMerge, Track,
)
from app.services import artist_merge, scan_library
from app.services.credits import parse_credit, resolve_artist

# Reuse the folder-scan fixtures and helpers.
from tests.test_library_scan import file_db, libs, _touch, _fake_probe, _count, _all  # noqa: F401


# ---------------------------------------------------------------------------
# Credit parsing (scan-time normalization)
# ---------------------------------------------------------------------------
def test_feat_credit_attaches_to_main_artist_and_keeps_text():
    # "Featuring", "feat." and "ft." all split to the main artist, keeping text.
    for raw in (
        "2Pac Featuring KC And Jojo",
        "2Pac feat. KC and JoJo",
        "2Pac ft KC and JoJo",
    ):
        parsed = parse_credit(raw)
        assert parsed.main == "2Pac"
        assert parsed.credited_as == raw


def test_ampersand_and_and_are_never_split():
    # "&" and "And" stay one artist (Simon & Garfunkel, Earth, Wind & Fire).
    for raw in ("Simon & Garfunkel", "Earth, Wind & Fire", "Hall and Oates"):
        parsed = parse_credit(raw)
        assert parsed.main == raw
        assert parsed.credited_as is None


# ---------------------------------------------------------------------------
# Merge then rescan does not recreate the source
# ---------------------------------------------------------------------------
def test_merge_moves_albums_and_tracks_and_removes_source(db_session):
    main = Artist(name="2Pac")
    feat = Artist(name="2Pac Featuring KC And Jojo")
    db_session.add_all([main, feat])
    db_session.flush()
    album = Album(artist_id=feat.id, title="How Do U Want It")
    db_session.add(album)
    db_session.flush()
    track = Track(album_id=album.id, title="How Do U Want It", track_number=1, disc_number=1)
    db_session.add(track)
    db_session.commit()

    record = artist_merge.merge(db_session, feat, main)
    db_session.commit()

    # Album moved to the target; source artist gone.
    assert db_session.get(Album, album.id).artist_id == main.id
    assert db_session.get(Artist, feat.id) is None
    # Credit text is kept on the moved album and track.
    assert db_session.get(Album, album.id).credited_as == "2Pac Featuring KC And Jojo"
    assert db_session.get(Track, track.id).credited_as == "2Pac Featuring KC And Jojo"
    # A durable alias was saved, name and (absent) mbid both routing to target.
    alias = db_session.scalar(select(ArtistAlias).where(ArtistAlias.name_key == "2pac featuring kc and jojo"))
    assert alias is not None and alias.target_artist_id == main.id
    # The merge record names the source for undo.
    assert record.source_name == "2Pac Featuring KC And Jojo"
    assert record.moved_album_ids == [str(album.id)]


def test_resolve_artist_routes_source_name_to_target(db_session):
    main = Artist(name="2Pac")
    db_session.add(main)
    db_session.flush()
    db_session.add(ArtistAlias(
        target_artist_id=main.id, name_key="2pac featuring kc and jojo",
        source_name="2Pac Featuring KC And Jojo", source_mbid=None,
    ))
    db_session.commit()

    name, mbid, target = resolve_artist(db_session, name="2Pac Featuring KC And Jojo")
    assert target is not None and target.id == main.id
    assert name == "2Pac"


def test_merge_then_rescan_does_not_recreate_the_source(file_db, libs, monkeypatch):
    _fake_probe(monkeypatch)
    # Two files on disk: the main artist and an "&" collaboration folder. The
    # scan never auto-splits "&", so "808 State And UB40" is its own artist
    # until an admin merges it (exactly Jon's "808 State" + "808 State And UB40").
    _touch(libs["music"] / "808 State" / "Ex El" / "01 - San Francisco.flac")
    _touch(libs["music"] / "808 State And UB40" / "One In Ten" / "01 - One In Ten.flac")

    def tags(path):
        name = Path(path).parts[-3]
        album = Path(path).parts[-2]
        return {"albumartist": name, "album": album, "title": "Song", "tracknumber": "1"}

    monkeypatch.setattr(scan_library, "read_tags", tags)

    # First scan: both folders land as separate artists.
    with file_db() as db:
        scan_library.scan_all(db)
        db.commit()
    names = {a.name for a in _all(file_db, Artist)}
    assert "808 State" in names and "808 State And UB40" in names

    # Admin merges the collaboration artist into 808 State.
    with file_db() as db:
        main = db.scalar(select(Artist).where(Artist.name == "808 State"))
        feat = db.scalar(select(Artist).where(Artist.name == "808 State And UB40"))
        artist_merge.merge(db, feat, main)
        db.commit()

    assert _count(file_db, Artist) == 1

    # Rescan: the alias resolves the collaboration folder to 808 State, so it is
    # NOT recreated.
    with file_db() as db:
        scan_library.scan_all(db)
        db.commit()
    names = {a.name for a in _all(file_db, Artist)}
    assert names == {"808 State"}, "the merged-away artist was recreated on rescan"
    # Both albums now hang off the one artist.
    with file_db() as db:
        main = db.scalar(select(Artist).where(Artist.name == "808 State"))
        n_albums = db.scalar(select(func.count(Album.id)).where(Album.artist_id == main.id))
    assert n_albums == 2


# ---------------------------------------------------------------------------
# Undo restores the source artist with its albums and tracks
# ---------------------------------------------------------------------------
def test_undo_restores_the_source_with_its_albums_and_tracks(db_session):
    main = Artist(name="808 State", mbid=str(uuid.UUID(int=1)))
    feat = Artist(name="808 State And UB40", mbid=str(uuid.UUID(int=2)))
    db_session.add_all([main, feat])
    db_session.flush()
    album = Album(artist_id=feat.id, title="One In Ten")
    db_session.add(album)
    db_session.flush()
    track = Track(album_id=album.id, title="One In Ten", track_number=1, disc_number=1)
    db_session.add(track)
    db_session.commit()

    record = artist_merge.merge(db_session, feat, main)
    db_session.commit()
    assert db_session.get(Album, album.id).artist_id == main.id

    restored = artist_merge.undo(db_session, record)
    db_session.commit()

    # Source artist is back, with its original name and mbid, and its album.
    assert restored.name == "808 State And UB40"
    assert restored.mbid == str(uuid.UUID(int=2))
    assert db_session.get(Album, album.id).artist_id == restored.id
    # The track rides along with its album.
    assert db_session.get(Track, track.id).album_id == album.id
    # The alias is gone, so a rescan would make the source again (undo is real).
    assert db_session.scalar(select(func.count(ArtistAlias.id))) == 0
    # The merge record is marked undone.
    assert db_session.get(ArtistMerge, record.id).undone_at is not None


def test_undo_twice_is_refused(db_session):
    main = Artist(name="A")
    feat = Artist(name="B")
    db_session.add_all([main, feat])
    db_session.flush()
    db_session.commit()
    record = artist_merge.merge(db_session, feat, main)
    db_session.commit()
    artist_merge.undo(db_session, record)
    db_session.commit()
    with pytest.raises(artist_merge.MergeError):
        artist_merge.undo(db_session, record)


def test_merge_into_self_is_refused(db_session):
    a = Artist(name="Solo")
    db_session.add(a)
    db_session.flush()
    db_session.commit()
    with pytest.raises(artist_merge.MergeError):
        artist_merge.merge(db_session, a, a)


# ---------------------------------------------------------------------------
# Endpoints are admin only and name what moves
# ---------------------------------------------------------------------------
def test_merge_endpoints_require_admin(db_session):
    """The merge, undo and preview endpoints depend on require_admin. A member
    client (no admin override) gets 401/403, never a successful merge."""
    from fastapi.testclient import TestClient

    from app.api.deps import current_user, get_db, require_admin
    from app.main import app
    from fastapi import HTTPException

    main = Artist(name="Main")
    feat = Artist(name="Feat")
    db_session.add_all([main, feat])
    db_session.flush()
    db_session.commit()

    def _override_db():
        yield db_session

    def _deny_admin():
        raise HTTPException(status_code=403, detail="admin_required")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_admin] = _deny_admin
    try:
        c = TestClient(app)
        r1 = c.post(f"/api/admin/artists/{feat.id}/merge", json={"target_id": str(main.id)})
        r2 = c.post(f"/api/admin/artists/merges/{uuid.uuid4()}/undo")
        r3 = c.get(f"/api/admin/artists/{feat.id}/merge-preview?target_id={main.id}")
        c.close()
    finally:
        app.dependency_overrides.clear()
    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403
    # No merge happened.
    assert db_session.get(Artist, feat.id) is not None


def test_merge_and_undo_endpoints_round_trip(client, db_session):
    """The admin client fixture drives a real merge then undo over HTTP."""
    main = Artist(name="Target")
    feat = Artist(name="Source Feat")
    db_session.add_all([main, feat])
    db_session.flush()
    album = Album(artist_id=feat.id, title="Collab")
    db_session.add(album)
    db_session.flush()
    db_session.add(Track(album_id=album.id, title="T", track_number=1, disc_number=1))
    db_session.commit()

    prev = client.get(f"/api/admin/artists/{feat.id}/merge-preview?target_id={main.id}")
    assert prev.status_code == 200
    assert prev.json()["albums"] == 1 and prev.json()["tracks"] == 1

    merged = client.post(f"/api/admin/artists/{feat.id}/merge", json={"target_id": str(main.id)})
    assert merged.status_code == 200
    merge_id = merged.json()["merge_id"]
    assert merged.json()["albums_moved"] == 1
    assert db_session.get(Artist, feat.id) is None

    listing = client.get(f"/api/admin/artists/{main.id}/merges")
    assert listing.status_code == 200
    assert any(m["merge_id"] == merge_id for m in listing.json())

    undone = client.post(f"/api/admin/artists/merges/{merge_id}/undo")
    assert undone.status_code == 200
    assert undone.json()["albums_restored"] == 1
    restored_id = undone.json()["restored_artist_id"]
    assert db_session.get(Artist, uuid.UUID(restored_id)) is not None
