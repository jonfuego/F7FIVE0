"""Art on the Continue rail (/api/continue-watching).

A music video release keeps `cover_path` as a path on the media drive, not a
servable URL, so the rail used to hand a disk path to the client and the tile
came up blank. The rail now uses the watched video's thumb, the same
art_overrides lookup every other tile uses, and never a disk path.
"""
from __future__ import annotations

import uuid

from app.models.art import (
    ENTITY_ALBUM, ENTITY_MUSIC_VIDEO, ROLE_COVER, ROLE_THUMB, ArtOverride,
)
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, MusicVideo, MusicVideoRelease, Track
from app.models.playback import WatchProgress

RAW_DISK_PATH = "N:\\Music Videos\\Skinny Puppy\\Show 1\\cover.jpg"


def _me(db_session):
    from app.api.deps import current_user
    from app.main import app

    user = app.dependency_overrides[current_user]()
    user = db_session.merge(user)
    db_session.flush()
    return user


def _in_progress(db_session, user, mf) -> None:
    db_session.add(WatchProgress(
        user_id=user.id, media_file_id=mf.id, position_sec=600, duration_sec=3600,
    ))


def _music_video_release(db_session, user, *, with_thumb: bool):
    artist = Artist(name="Skinny Puppy")
    db_session.add(artist)
    db_session.flush()
    rel = MusicVideoRelease(
        artist_id=artist.id, title="Birmingham (Board Mix)",
        source_subpath="Show 1", cover_path=RAW_DISK_PATH,
    )
    db_session.add(rel)
    db_session.flush()
    mv = MusicVideo(
        release_id=rel.id, artist_id=artist.id, title="Dig It",
        source_subpath="dig-it.mp4",
    )
    db_session.add(mv)
    db_session.flush()
    mf = MediaFile(
        kind=MediaKind.music_video, ref_id=mv.id,
        path=f"/mv/dig-it-{uuid.uuid4()}.mp4",
        scan_state=ScanState.ready, duration_sec=3600,
    )
    db_session.add(mf)
    db_session.flush()
    if with_thumb:
        db_session.add(ArtOverride(
            entity_kind=ENTITY_MUSIC_VIDEO, entity_id=mv.id, role=ROLE_THUMB,
            local_path="music_video/x/thumb.jpg", source_kind="frame",
            set_by=user.id,
        ))
    _in_progress(db_session, user, mf)
    db_session.commit()
    return rel, mv


def test_music_video_release_uses_the_video_thumb(client, db_session):
    user = _me(db_session)
    rel, mv = _music_video_release(db_session, user, with_thumb=True)

    r = client.get("/api/continue-watching")
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["kind"] == "music_video_release"
    assert items[0]["id"] == str(rel.id)
    assert items[0]["poster_path"].startswith(
        f"/api/art/{ENTITY_MUSIC_VIDEO}/{mv.id}/{ROLE_THUMB}"
    )


def test_music_video_release_never_sends_a_disk_path(client, db_session):
    user = _me(db_session)
    _music_video_release(db_session, user, with_thumb=False)

    r = client.get("/api/continue-watching")
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["poster_path"] is None


def test_album_uses_its_cover_override(client, db_session):
    user = _me(db_session)
    artist = Artist(name="Skinny Puppy")
    db_session.add(artist)
    db_session.flush()
    album = Album(artist_id=artist.id, title="12 Inch Anthology")
    db_session.add(album)
    db_session.flush()
    track = Track(album_id=album.id, title="Dig It", track_number=1)
    db_session.add(track)
    db_session.flush()
    mf = MediaFile(
        kind=MediaKind.track, ref_id=track.id,
        path=f"/music/dig-it-{uuid.uuid4()}.flac",
        scan_state=ScanState.ready, duration_sec=3600,
    )
    db_session.add(mf)
    db_session.flush()
    db_session.add(ArtOverride(
        entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER,
        local_path="album/x/cover.jpg", source_kind="local", set_by=user.id,
    ))
    _in_progress(db_session, user, mf)
    db_session.commit()

    r = client.get("/api/continue-watching")
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["kind"] == "album"
    assert items[0]["poster_path"].startswith(
        f"/api/art/{ENTITY_ALBUM}/{album.id}/{ROLE_COVER}"
    )
