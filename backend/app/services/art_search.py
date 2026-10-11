"""Aggregate candidate art from every configured source.

For a given (kind, entity_id) pair, this asks each source that applies to
the kind for images, normalizes them into a flat list of
`{source, ref, url, preview_url, label}` dicts, and returns it. The frontend
renders each candidate as a tile in the modal's Search tab (the `source` tag
labels the tile, `preview_url` is the small image the tile loads); the admin
clicks one and the backend downloads `url` (full size) through the existing
`fetch_and_save_url`. `preview_url` is always set: a source that has no
smaller variant gets `url` there (see `_ensure_previews`).

Sources per kind:
  artist / music video -> Lidarr, TheAudioDB, iTunes (iTunes is music-video
    only, see `_artist_candidates`).
  movie                -> Radarr, TMDB.
  series               -> Sonarr, TMDB.
  album                -> Lidarr, Cover Art Archive.
*arr is one source among several, not the gatekeeper: with no *arr key set,
the other sources still answer.

Each *arr exposes an `images` array on its detail endpoint with entries
shaped like `{coverType, url, remoteUrl}`. We prefer `remoteUrl` because
that is what the local *arr proxy resolves to a public CDN. Entries
without a `remoteUrl` are skipped (Lidarr's `disc` covers in particular
sometimes lack one).

When the local entity has no upstream id (music-videos-only artists, for
instance), we fall back to the `*/lookup` endpoints with the entity's
title as the search term. The first result's images become the candidate
list. Lookup is best-effort: a missing match returns an empty list, not
an error, so the modal can show a clean "No candidates" state.

`search_candidates` returns the flat list (used by the apply path to re-
derive a picked URL). `search_candidates_with_notes` returns the same
list plus friendly, human-readable notes about sources that failed or are
not set up, for the modal's callouts. One source failing never drops the
others: each source is tried independently and its failure becomes a note.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.art import (
    ENTITY_ALBUM, ENTITY_ARTIST, ENTITY_MOVIE, ENTITY_MUSIC_VIDEO,
    ENTITY_SERIES,
)
from app.models.movie import Movie
from app.models.music import Album, Artist, MusicVideo
from app.models.tv import Series
from app.services import tmdb_key
from app.services.arr import LidarrClient, RadarrClient, SonarrClient
from app.services.arr._base import ArrClientError
from app.services.art_sources import audiodb as audiodb_source
from app.services.art_sources import coverart as coverart_source
from app.services.art_sources import itunes as itunes_source
from app.services.art_sources import previews
from app.services.art_sources import tmdb as tmdb_source


log = logging.getLogger("f7five0.art_search")


def search_candidates(
    db: Session,
    *,
    kind: str,
    entity_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return a flat list of candidate art for the entity.

    Each entry: `{source, ref, url, preview_url, label}`. `source` is the
    provider name (`lidarr` / `radarr` / `sonarr` / `tmdb` / `audiodb` /
    `itunes` / `coverart`). `ref` is the candidate's upstream identifier (the
    image URL itself today). `url` is the full-size image URL that applying
    downloads. `preview_url` is a small copy for the modal's tile (the same
    as `url` when the source has no smaller variant). `label` is the display
    string the modal puts under the thumbnail.

    Empty list when no source returns anything useful. Individual source
    failures are swallowed here; use `search_candidates_with_notes` when
    the caller wants to surface them.
    """
    candidates, _notes = search_candidates_with_notes(
        db, kind=kind, entity_id=entity_id,
    )
    return candidates


def search_candidates_with_notes(
    db: Session,
    *,
    kind: str,
    entity_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return `(candidates, notes)` for the entity.

    `notes` are short, friendly strings for the modal to show as callouts:
    a source that did not answer ("TheAudioDB did not answer.") or one that
    is not set up ("Movies and TV search TMDB. Add a TMDB key in Admin to
    search here."). No raw error codes reach this list.
    """
    if kind == ENTITY_ARTIST:
        found = _artist_candidates(db, entity_id)
    elif kind == ENTITY_MOVIE:
        found = _movie_candidates(db, entity_id)
    elif kind == ENTITY_SERIES:
        found = _series_candidates(db, entity_id)
    elif kind == ENTITY_MUSIC_VIDEO:
        found = _music_video_candidates(db, entity_id)
    elif kind == ENTITY_ALBUM:
        found = _album_candidates(db, entity_id)
    else:
        return [], []
    candidates, notes = found
    return _ensure_previews(candidates), notes


# ---------------------------------------------------------------------------
# Per-kind aggregators
# ---------------------------------------------------------------------------
def _artist_candidates(
    db: Session, entity_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Artist art: real portraits and fanart only.

    Lidarr's get_artist returns artist-level images (poster/fanart/
    banner/logo) which are genuine artist artwork. AudioDB likewise
    returns artist portraits. iTunes is intentionally skipped here
    because the unauthenticated Search API only surfaces album covers,
    and album art doesn't belong on the artist tile. The music-video
    aggregator still uses iTunes since album art is a defensible thumb
    for a video.
    """
    artist = db.get(Artist, entity_id)
    if artist is None:
        return [], []
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    _run(
        notes, "Lidarr",
        lambda: _lidarr_artist_images(artist.lidarr_id, artist.name),
        out,
    )
    _run(
        notes, "TheAudioDB",
        lambda: _audiodb_artist_images(artist.name), out,
    )
    if not _lidarr().configured:
        notes.append(_ARR_MISSING["lidarr"])
    return _dedupe_by_url(out), notes


def _movie_candidates(
    db: Session, entity_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str]]:
    movie = db.get(Movie, entity_id)
    if movie is None:
        return [], []
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    _run(notes, "Radarr", lambda: _radarr_movie_images(movie), out)
    if movie.tmdb_id and tmdb_key.get():
        _run(
            notes, "TMDB",
            lambda: tmdb_source.movie_images(tmdb_key.get(), movie.tmdb_id),
            out,
        )
    elif not tmdb_key.get():
        notes.append(_TMDB_MISSING)
    if not _radarr().configured:
        notes.append(_ARR_MISSING["radarr"])
    return _dedupe_by_url(out), notes


def _series_candidates(
    db: Session, entity_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str]]:
    series = db.get(Series, entity_id)
    if series is None:
        return [], []
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    _run(notes, "Sonarr", lambda: _sonarr_series_images(series), out)
    if series.tmdb_id and tmdb_key.get():
        _run(
            notes, "TMDB",
            lambda: tmdb_source.series_images(tmdb_key.get(), series.tmdb_id),
            out,
        )
    elif not tmdb_key.get():
        notes.append(_TMDB_MISSING)
    if not _sonarr().configured:
        notes.append(_ARR_MISSING["sonarr"])
    return _dedupe_by_url(out), notes


def _music_video_candidates(
    db: Session, entity_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Music videos do not have their own *arr representation. Surface
    the parent artist's Lidarr / AudioDB / iTunes images so the admin
    can pick a relevant portrait, fanart, or album cover as the per-
    video thumb."""
    mv = db.get(MusicVideo, entity_id)
    if mv is None:
        return [], []
    artist = db.get(Artist, mv.artist_id)
    if artist is None:
        return [], []
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    _run(
        notes, "Lidarr",
        lambda: _lidarr_artist_images(artist.lidarr_id, artist.name), out,
    )
    _run(notes, "TheAudioDB", lambda: _audiodb_artist_images(artist.name), out)
    _run(notes, "iTunes", lambda: _itunes_artist_images(artist.name), out)
    if not _lidarr().configured:
        notes.append(_ARR_MISSING["lidarr"])
    return _dedupe_by_url(out), notes


def _album_candidates(
    db: Session, entity_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Album cover art: Lidarr album images plus the Cover Art Archive,
    keyed by the album's MusicBrainz release-group MBID."""
    album = db.get(Album, entity_id)
    if album is None:
        return [], []
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    _run(notes, "Lidarr", lambda: _lidarr_album_images(album), out)
    _run(
        notes, "Cover Art Archive",
        lambda: coverart_source.release_group_images(album.mbid), out,
    )
    if not _lidarr().configured:
        notes.append(_ARR_MISSING["lidarr"])
    return _dedupe_by_url(out), notes


# ---------------------------------------------------------------------------
# Friendly notes
# ---------------------------------------------------------------------------
_TMDB_MISSING = (
    "Movies and TV search TMDB. Add a TMDB key in Admin to search here."
)
_ARR_MISSING = {
    "lidarr": "Connect Lidarr to also search your Lidarr library.",
    "radarr": "Connect Radarr to also search your Radarr library.",
    "sonarr": "Connect Sonarr to also search your Sonarr library.",
}


def _run(
    notes: list[str],
    display: str,
    fn: Callable[[], list[dict[str, Any]]],
    out: list[dict[str, Any]],
) -> None:
    """Run one source. On any failure, record a friendly note and move on
    so a single dead source never drops the others' results."""
    # Broad catch on purpose: a source is best-effort. ArrClientError,
    # ProviderError, and any transport error all become one friendly note
    # so one dead source never drops the others' results.
    try:
        out.extend(fn())
    except Exception as exc:  # noqa: BLE001
        log.warning("art source %s failed: %s", display, exc)
        notes.append(f"{display} did not answer.")


# ---------------------------------------------------------------------------
# *arr image helpers
# ---------------------------------------------------------------------------
def _radarr_movie_images(movie: Movie) -> list[dict[str, Any]]:
    client = _radarr()
    if not client.configured:
        return []
    images: list[dict[str, Any]] = []
    try:
        if movie.radarr_id is not None:
            payload = client.get_movie(movie.radarr_id)
            images = list(payload.get("images") or [])
        if not images and movie.title:
            results = client.movie_lookup(movie.title)
            chosen = _pick_lookup_match(
                results, imdb_id=movie.imdb_id, tmdb_id=movie.tmdb_id,
            )
            if chosen is not None:
                images = list(chosen.get("images") or [])
    finally:
        client.close()
    return _normalize_images("radarr", "Radarr", images)


def _sonarr_series_images(series: Series) -> list[dict[str, Any]]:
    client = _sonarr()
    if not client.configured:
        return []
    images: list[dict[str, Any]] = []
    try:
        if series.sonarr_id is not None:
            payload = client.get_series(series.sonarr_id)
            images = list(payload.get("images") or [])
        if not images and series.title:
            results = client.series_lookup(series.title)
            chosen = _pick_lookup_match(
                results, tvdb_id=series.tvdb_id, tmdb_id=series.tmdb_id,
            )
            if chosen is not None:
                images = list(chosen.get("images") or [])
    finally:
        client.close()
    return _normalize_images("sonarr", "Sonarr", images)


def _lidarr_album_images(album: Album) -> list[dict[str, Any]]:
    client = _lidarr()
    if not client.configured:
        return []
    images: list[dict[str, Any]] = []
    try:
        if album.mbid:
            results = client.album_lookup(album.title or album.mbid)
            chosen = _pick_lookup_match(results, foreignAlbumId=album.mbid)
            if chosen is None and results:
                chosen = results[0]
            if chosen is not None:
                images = list((chosen or {}).get("images") or [])
    finally:
        client.close()
    return _normalize_images("lidarr", "Lidarr", images)


# ---------------------------------------------------------------------------
# Art-source helpers
# ---------------------------------------------------------------------------
def _itunes_artist_images(name: Optional[str]) -> list[dict[str, Any]]:
    """Best-effort iTunes album-art fallback for an artist."""
    if not settings.itunes_enabled or not name:
        return []
    return itunes_source.search_artist(name)


def _audiodb_artist_images(name: Optional[str]) -> list[dict[str, Any]]:
    """TheAudioDB portraits/fanart fallback for an artist."""
    if not settings.audiodb_api_key or not name:
        return []
    return audiodb_source.search_artist(settings.audiodb_api_key, name)


def _ensure_previews(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every candidate a `preview_url`.

    Sources that know a size scheme set their own. Anything missing one
    shows its full-size `url` in the tile.
    """
    for item in items:
        if not item.get("preview_url"):
            item["preview_url"] = item.get("url")
    return items


def _dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable dedupe across sources. First occurrence wins so Lidarr/Radarr
    sit above iTunes/TMDB when both return the same upstream URL (rare in
    practice but worth handling)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def _lidarr_artist_images(
    lidarr_id: Optional[int], name: Optional[str],
) -> list[dict[str, Any]]:
    client = _lidarr()
    if not client.configured:
        return []
    images: list[dict[str, Any]] = []
    try:
        if lidarr_id is not None:
            payload = client.get_artist(lidarr_id)
            images = list(payload.get("images") or [])
        if not images and name:
            results = client.artist_lookup(name)
            if results:
                images = list((results[0] or {}).get("images") or [])
    finally:
        client.close()
    return _normalize_images("lidarr", "Lidarr", images)


# *arr cover types that are 16:9 art, so a TMDB URL uses the backdrop sizes.
_BACKDROP_COVER_TYPES = frozenset({"fanart", "banner", "background", "screenshot"})


def _normalize_images(
    source: str, label_prefix: str, images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map *arr `images` entries to the modal's wire shape and dedupe.

    *arr returns entries like `{coverType: "poster", url: "/...", remoteUrl: "https://..."}`.
    We rely on `remoteUrl` because the local `/MediaCover/...` urls aren't
    reachable from the browser. Entries without one are dropped. Cover
    type drives the label; the ref is the remoteUrl so the from-search
    endpoint can re-derive it without the modal echoing a full URL back.
    """
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for img in images:
        if not isinstance(img, dict):
            continue
        url = img.get("remoteUrl")
        if not isinstance(url, str) or not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        cover_type = img.get("coverType") or "image"
        backdrop = cover_type in _BACKDROP_COVER_TYPES
        out.append({
            "source": source,
            "ref": url,
            "url": url,
            "preview_url": previews.preview_for(url, backdrop=backdrop) or url,
            "label": f"{label_prefix} {cover_type}",
        })
    return out


def _pick_lookup_match(
    results: list[dict[str, Any]], **keys: Any,
) -> Optional[dict[str, Any]]:
    """Pick the lookup result whose external IDs match the local entity.

    Falls through to the first result if no key matches; *arr's lookup
    returns the closest match first. We never invent a match; the caller
    handles the empty case by returning an empty candidate list.
    """
    if not results:
        return None
    for r in results:
        for k, v in keys.items():
            if v is None:
                continue
            if r.get(k) == v:
                return r
    return results[0]


def _lidarr() -> LidarrClient:
    return LidarrClient(settings.lidarr_url, settings.lidarr_api_key)


def _radarr() -> RadarrClient:
    return RadarrClient(settings.radarr_url, settings.radarr_api_key)


def _sonarr() -> SonarrClient:
    return SonarrClient(settings.sonarr_url, settings.sonarr_api_key)


__all__ = [
    "search_candidates", "search_candidates_with_notes", "ArrClientError",
]
