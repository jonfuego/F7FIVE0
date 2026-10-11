"""Give artists with no picture one, automatically.

An artist with no `artist` / `thumb` art row (no sidecar image, no *arr
picture, nothing an admin chose) gets a picture from TheAudioDB (by
MusicBrainz id when the artist has one, else an exact name match) and, failing
that, Deezer (an exact name match, see `art_sources/names.py`). It is saved
with `source_kind` `artist_auto`, which only this job writes.

`artist_auto` behaves like the music-video `frame` grab: it is the weakest art
there is. This job never writes over any existing art row, whatever its
`source_kind` (a final check runs after the download, right before the save),
and every other writer replaces it: the folder scan's sidecar import
(`scan_library._SCANNER_SOURCES`), the *arr sync (`art._AUTO_SOURCE_KINDS`),
and every admin path (upload, paste URL, pick from search), which overwrite
whatever is there.

Politeness and reruns:
  - walks artists in id order in batches of `batch_size`, one commit per
    artist, and waits `pause_sec` after every artist it had to ask the
    network about;
  - an artist nobody had a picture for is remembered in the `app_settings` key
    `artist_art_autofill_misses` and not asked again for `RETRY_DAYS` days
    (sooner if the artist is renamed), so the run that follows every scan does
    not repeat the same lookups; a lookup that errored (service down, quota)
    is not remembered and is tried again next run;
  - a run that sees `MAX_CONSECUTIVE_ERRORS` services failures in a row stops
    (the next scan queues another);
  - a second run finds nothing to do and creates nothing.

The scheduler runs it after boot and after each music / music videos scan
(`scheduler.trigger_artist_art_autofill`, one job id, so queueing it again
never stacks two runs).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.art import (
    ArtOverride, ENTITY_ARTIST, ROLE_THUMB, SOURCE_ARTIST_AUTO,
)
from app.models.music import Artist
from app.services import app_settings
from app.services.art import (
    SYSTEM_USER_ID, ArtValidationError, fetch_url_bytes, save_upload_bytes,
)
from app.services.art_sources import audiodb as audiodb_source
from app.services.art_sources import deezer as deezer_source


log = logging.getLogger("f7five0.artist_art_autofill")

MISSES_KEY = "artist_art_autofill_misses"
# How long "nobody has a picture for this artist" is believed.
RETRY_DAYS = 30
# Stop a run after this many service failures in a row.
MAX_CONSECUTIVE_ERRORS = 5
# Names that are not an artist, so a picture for them would be wrong.
_SKIP_NAMES = frozenset({
    "various artists", "various", "va", "unknown artist", "unknown",
    "no artist", "soundtrack", "original soundtrack",
})


def autofill_artist_art(
    db: Session,
    *,
    batch_size: int = 25,
    pause_sec: Optional[float] = None,
    now: Optional[datetime] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fill thumb art for artists that have none. Returns how many artists got
    a picture (0 on a second run). Never raises for a service or image
    failure; those only skip the artist."""
    if not settings.artist_art_autofill_enabled:
        return 0
    if pause_sec is None:
        pause_sec = max(0.0, settings.artist_art_autofill_pause_sec)
    now = now or datetime.now(timezone.utc)
    misses = _load_misses(db, now)
    filled = 0
    errors_in_row = 0
    last_id = None
    while True:
        rows = _next_batch(db, last_id, batch_size)
        if not rows:
            break
        last_id = rows[-1][0]
        for artist_id, name, mbid in rows:
            if not name or name.strip().casefold() in _SKIP_NAMES:
                continue
            if _recent_miss(misses, artist_id, name):
                continue
            outcome, url = _find_picture(name, mbid)
            if outcome == "error":
                errors_in_row += 1
            elif outcome in ("found", "none"):
                errors_in_row = 0
            if outcome == "none":
                misses[str(artist_id)] = {"n": name, "d": now.date().isoformat()}
            elif outcome == "found":
                if _save(db, artist_id, name, url):
                    filled += 1
                else:
                    misses[str(artist_id)] = {"n": name, "d": now.date().isoformat()}
            if outcome != "skipped" and pause_sec > 0:
                sleep(pause_sec)
            if errors_in_row >= MAX_CONSECUTIVE_ERRORS:
                log.warning(
                    "artist art auto-fill stopping: %d service failures in a row",
                    errors_in_row,
                )
                _store_misses(db, misses)
                db.commit()
                return filled
        _store_misses(db, misses)
        db.commit()
    return filled


def _next_batch(db: Session, after_id, limit: int) -> list[tuple]:
    """Artists with no thumb art row, in id order, after `after_id`."""
    has_art = exists().where(
        ArtOverride.entity_kind == ENTITY_ARTIST,
        ArtOverride.entity_id == Artist.id,
        ArtOverride.role == ROLE_THUMB,
    )
    stmt = (
        select(Artist.id, Artist.name, Artist.mbid)
        .where(~has_art)
        .order_by(Artist.id)
        .limit(limit)
    )
    if after_id is not None:
        stmt = stmt.where(Artist.id > after_id)
    return [tuple(r) for r in db.execute(stmt).all()]


def _find_picture(name: str, mbid: Optional[str]) -> tuple[str, Optional[str]]:
    """`("found", url)`, `("none", None)` when every source answered and had
    nothing, or `("error", None)` when a source could not answer and nothing
    else found a picture."""
    failed = False
    key = settings.audiodb_api_key
    if key:
        try:
            url = audiodb_source.thumb_url(key, name, mbid)
        except audiodb_source.AudioDBError as exc:
            failed = True
            log.info("artist art auto-fill: TheAudioDB failed for %r: %s", name, exc)
        else:
            if url:
                return "found", url
    if settings.deezer_enabled:
        try:
            url = deezer_source.best_picture(name)
        except deezer_source.DeezerError as exc:
            failed = True
            log.info("artist art auto-fill: Deezer failed for %r: %s", name, exc)
        else:
            if url:
                return "found", url
    if failed:
        return "error", None
    if not key and not settings.deezer_enabled:
        return "skipped", None
    return "none", None


def _save(db: Session, artist_id, name: str, url: str) -> bool:
    """Download and save `url` as the artist's auto-filled thumb. False when
    the image was unusable or the artist got art in the meantime."""
    try:
        data = fetch_url_bytes(url)
    except ArtValidationError as exc:
        log.info("artist art auto-fill: image for %r skipped: %s", name, exc)
        return False
    # The download took a moment; an admin or a scan may have set art since the
    # query. Existing art of any kind wins.
    if db.get(ArtOverride, (ENTITY_ARTIST, artist_id, ROLE_THUMB)) is not None:
        return False
    try:
        save_upload_bytes(
            db, entity_kind=ENTITY_ARTIST, entity_id=artist_id, role=ROLE_THUMB,
            data=data, set_by_user_id=SYSTEM_USER_ID,
            source_kind=SOURCE_ARTIST_AUTO, source_ref=url[:2000],
        )
    except ArtValidationError as exc:
        log.info("artist art auto-fill: image for %r rejected: %s", name, exc)
        return False
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Misses: artists nobody had a picture for
# ---------------------------------------------------------------------------
def _load_misses(db: Session, now: datetime) -> dict[str, dict]:
    stored = app_settings.get(db, MISSES_KEY) or {}
    cutoff = (now - timedelta(days=RETRY_DAYS)).date().isoformat()
    return {
        k: v for k, v in stored.items()
        if isinstance(v, dict) and str(v.get("d", "")) > cutoff
    }


def _recent_miss(misses: dict[str, dict], artist_id, name: str) -> bool:
    entry = misses.get(str(artist_id))
    return entry is not None and entry.get("n") == name


def _store_misses(db: Session, misses: dict[str, dict]) -> None:
    app_settings.put(db, MISSES_KEY, misses)
