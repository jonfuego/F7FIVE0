"""Provider keys and orphan relinking for watch-history and track-play rows.

A provider key is a stable string that survives file deletion and
re-scanning, built from an external provider id rather than the internal
UUID. When a new MediaFile row appears, the scan checks orphaned history
rows (media_file_id IS NULL) for a matching ref_key so play history is
preserved across rescans and library rebuilds.

Supported keys:
  movie    tmdb:<tmdb_id>
  episode  tvdb:<series_tvdb_id>:s<season>e<episode>
           tmdb:<series_tmdb_id>:s<season>e<episode>   (fallback when no tvdb)
  track    mbrec:<track_mbid>
"""
from __future__ import annotations

from typing import Optional, Union

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.models.media_file import MediaFile, MediaKind
from app.models.movie import Movie
from app.models.music import Track
from app.models.playback import WatchHistory
from app.models.track_play import TrackPlay
from app.models.tv import Episode, Series


def provider_key(
    db: Session,
    kind: str,
    item: Union[Movie, Episode, Track],
) -> Optional[str]:
    """Build a stable provider key for an entity, or None if no provider id.

    - Movie: ``tmdb:<tmdb_id>``
    - Episode: ``tvdb:<series_tvdb_id>:s<season>e<episode>`` (fallback
      ``tmdb:<series_tmdb_id>:s<season>e<episode>`` when the series has
      no TVDB id)
    - Track: ``mbrec:<mbid>`` (None when the track has no MusicBrainz id)
    """
    if kind == "movie":
        movie: Movie = item  # type: ignore[assignment]
        if movie.tmdb_id is None:
            return None
        return f"tmdb:{movie.tmdb_id}"

    if kind == "episode":
        episode: Episode = item  # type: ignore[assignment]
        series = db.get(Series, episode.series_id)
        if series is None:
            return None
        season = episode.season_number
        ep = episode.episode_number
        if series.tvdb_id is not None:
            return f"tvdb:{series.tvdb_id}:s{season}e{ep}"
        if series.tmdb_id is not None:
            return f"tmdb:{series.tmdb_id}:s{season}e{ep}"
        return None

    if kind == "track":
        track: Track = item  # type: ignore[assignment]
        if track.mbid is None:
            return None
        return f"mbrec:{track.mbid}"

    return None


def relink_history(db: Session, mf: MediaFile) -> None:
    """Relink orphaned watch_history (and track_plays for tracks) to a new MediaFile row.

    Called after a new MediaFile row is flushed. Matches orphaned rows (those
    with media_file_id IS NULL) by last_path first, then ref_key, then
    ref_kind + ref_id. All matching rows are updated in one pass.
    """
    path = mf.path
    ref_kind_str = mf.kind.value
    ref_id = mf.ref_id

    # Build provider key for the new file to match ref_key on orphaned rows.
    key: Optional[str] = None
    if mf.kind == MediaKind.movie:
        item = db.get(Movie, ref_id)
        if item:
            key = provider_key(db, "movie", item)
    elif mf.kind == MediaKind.episode:
        item = db.get(Episode, ref_id)
        if item:
            key = provider_key(db, "episode", item)
    elif mf.kind == MediaKind.track:
        item = db.get(Track, ref_id)
        if item:
            key = provider_key(db, "track", item)

    # Relink WatchHistory rows.
    conds = [WatchHistory.last_path == path]
    if key:
        conds.append(WatchHistory.ref_key == key)
    conds.append(
        (WatchHistory.ref_kind == ref_kind_str) & (WatchHistory.ref_id == ref_id)
    )
    db.execute(
        update(WatchHistory)
        .where(WatchHistory.media_file_id.is_(None))
        .where(or_(*conds))
        .values(media_file_id=mf.id)
    )

    # Relink TrackPlay rows for track files.
    if mf.kind == MediaKind.track:
        tp_conds = [TrackPlay.last_path == path]
        if key:
            tp_conds.append(TrackPlay.ref_key == key)
        db.execute(
            update(TrackPlay)
            .where(TrackPlay.track_id.is_(None))
            .where(or_(*tp_conds))
            .values(track_id=ref_id)
        )
