"""Season posters for the season thumbs on the TV show page.

A season poster is an `art_overrides` row (entity kind `season`, entity id =
`seasons.id`, role `poster`), so it goes through the same pipeline as every
other picture: `save_upload_bytes` stores it under the art root with its 300
and 600 px WebP copies, and `/api/art/season/<id>/poster` serves it. The old
`seasons.poster_path` column stays unused, like the other legacy art columns.

Where a picture comes from, strongest first:
1. An admin pick (upload or URL through the admin art endpoints): never
   replaced by anything below.
2. A folder sidecar, read by the folder scan (scan_library): the Kodi / Plex /
   Jellyfin names in the show folder (`season01-poster.jpg`,
   `season1-poster.jpg`, `season-specials-poster.jpg`), or `poster.*` /
   `folder.*` / `cover.*` inside the season folder. A sidecar replaces an
   earlier TMDB pick.
3. The season image Sonarr reports for a Sonarr-managed show (sync).
4. The TMDB season poster, when a TMDB key is set and the show has a TMDB id.
   Only fills a season with no picture at all.
With none of these the web shows the show poster on the thumb.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.art import ArtOverride, ENTITY_SEASON, ROLE_POSTER
from app.models.tv import Season, Series

log = logging.getLogger("f7five0.season_art")

IMAGE_EXTS = ("jpg", "jpeg", "png", "webp")
# Names used for a poster that sits inside the season folder itself.
_IN_FOLDER_STEMS = ("poster", "folder", "cover")


def show_folder_stems(season_number: int) -> tuple[str, ...]:
    """Sidecar names (no extension, lowercase) for a season poster that sits
    in the show folder, most specific first."""
    if season_number == 0:
        return ("season-specials-poster", "season00-poster", "season0-poster", "specials-poster")
    padded, plain = f"season{season_number:02d}-poster", f"season{season_number}-poster"
    return (padded,) if padded == plain else (padded, plain)


def _first_image(folder: str, stems: Iterable[str]) -> Optional[str]:
    try:
        names = {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return None
    for stem in stems:
        for ext in IMAGE_EXTS:
            hit = names.get(f"{stem}.{ext}")
            if hit and os.path.isfile(os.path.join(folder, hit)):
                return os.path.join(folder, hit)
    return None


def find_season_poster(
    show_dir: str, season_number: int, season_dirs: Iterable[str] = (),
) -> Optional[str]:
    """Path of the poster image for one season of the show in `show_dir`, or
    None. The show-folder names win over a poster inside the season folder
    (`season_dirs`: the folders that hold this season's episodes; the show
    folder itself is skipped there, since its poster.* is the show poster)."""
    hit = _first_image(show_dir, show_folder_stems(season_number))
    if hit:
        return hit
    show_norm = os.path.normcase(os.path.normpath(show_dir))
    for folder in sorted(set(season_dirs)):
        if os.path.normcase(os.path.normpath(folder)) == show_norm:
            continue
        hit = _first_image(folder, _IN_FOLDER_STEMS)
        if hit:
            return hit
    return None


def _season_rows(db: Session, series_id: uuid.UUID) -> dict[int, Season]:
    rows = db.scalars(select(Season).where(Season.series_id == series_id)).all()
    return {s.season_number: s for s in rows}


def apply_sonarr_season_posters(
    db: Session,
    series: Series,
    seasons_payload: Optional[list[dict[str, Any]]],
    *,
    arr_base_url: str = "",
    arr_api_key: str = "",
) -> int:
    """Download the season images from a Sonarr series payload (`seasons[]`,
    each with `seasonNumber` and `images`) for the seasons F7FIVE0 has rows
    for. Admin and folder art are kept (download_art_on_sync's rules).
    Returns how many season posters were written or already current."""
    from app.services.art import download_art_on_sync

    if not seasons_payload:
        return 0
    rows = _season_rows(db, series.id)
    done = 0
    for entry in seasons_payload:
        if not isinstance(entry, dict):
            continue
        num = entry.get("seasonNumber")
        season = rows.get(num) if isinstance(num, int) else None
        images = entry.get("images") or []
        if season is None or not images:
            continue
        row = download_art_on_sync(
            db,
            entity_kind=ENTITY_SEASON, entity_id=season.id, role=ROLE_POSTER,
            images=images, cover_type="poster", source_kind="sonarr",
            arr_base_url=arr_base_url, arr_api_key=arr_api_key,
        )
        if row is not None:
            done += 1
    return done


def apply_tmdb_season_posters(
    db: Session, series: Series, tmdb_payload: Optional[dict[str, Any]],
) -> int:
    """Fetch TMDB season posters (from a `/tv/<id>` payload's `seasons[]`) for
    seasons that have no picture at all. Never replaces existing art. Returns
    how many were saved."""
    from app.services.art import (
        ArtValidationError, SYSTEM_USER_ID, fetch_and_save_url,
    )

    if not tmdb_payload:
        return 0
    rows = _season_rows(db, series.id)
    saved = 0
    for entry in tmdb_payload.get("seasons") or []:
        if not isinstance(entry, dict):
            continue
        num = entry.get("season_number")
        path = entry.get("poster_path")
        season = rows.get(num) if isinstance(num, int) else None
        if season is None or not isinstance(path, str) or not path.startswith("/"):
            continue
        if db.get(ArtOverride, (ENTITY_SEASON, season.id, ROLE_POSTER)) is not None:
            continue
        try:
            fetch_and_save_url(
                db, entity_kind=ENTITY_SEASON, entity_id=season.id, role=ROLE_POSTER,
                url=f"https://image.tmdb.org/t/p/w780{path}",
                set_by_user_id=SYSTEM_USER_ID, source_kind="tmdb",
            )
            saved += 1
        except ArtValidationError as exc:
            log.warning("tmdb season poster skipped for %s season %s: %s", series.id, num, exc)
    return saved


def fill_tmdb_season_posters(db: Session, series: Series) -> int:
    """Look up the show on TMDB (cached) and fill seasons that have no
    picture. A clean no-op without a TMDB key, a TMDB id, or a bare season."""
    from app.services import tmdb_key

    if not series.tmdb_id or not tmdb_key.get():
        return 0
    rows = _season_rows(db, series.id)
    if not rows:
        return 0
    have = set(db.scalars(
        select(ArtOverride.entity_id).where(
            ArtOverride.entity_kind == ENTITY_SEASON,
            ArtOverride.role == ROLE_POSTER,
            ArtOverride.entity_id.in_([s.id for s in rows.values()]),
        )
    ).all())
    if all(s.id in have for s in rows.values()):
        return 0
    from app.services.metadata._base import ProviderError
    from app.services.metadata.tmdb import TMDBClient
    try:
        with TMDBClient() as cli:
            payload = cli.get_series(int(series.tmdb_id))
    except ProviderError as exc:
        log.warning("tmdb tv fetch for season posters failed for %s: %s", series.id, exc)
        return 0
    return apply_tmdb_season_posters(db, series, payload)


def season_poster_urls(db: Session, series_id: uuid.UUID) -> dict[int, str]:
    """`{season number: art URL}` for the seasons of a show that have a
    poster. Seasons without one are absent (the web uses the show poster)."""
    from app.services.art import resolve_art_batch

    rows = _season_rows(db, series_id)
    if not rows:
        return {}
    found = resolve_art_batch(
        db, entity_kind=ENTITY_SEASON, entity_ids=[s.id for s in rows.values()],
        role=ROLE_POSTER,
    )
    return {num: found[s.id] for num, s in rows.items() if s.id in found}
