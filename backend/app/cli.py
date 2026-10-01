"""Small operator CLI. Run from the repo root:

    .\\backend\\.venv\\Scripts\\Activate.ps1
    $env:PYTHONPATH="$PWD\\backend"
    python -m app.cli create-admin --username admin --name "Your Name"

Prompts for the password. Use this once to seed the first admin; after that,
use the `/api/auth/users` endpoint as an authenticated admin.
"""
from __future__ import annotations

import argparse
import getpass
import os
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import db_session
from app.models.art import (
    ArtOverride, ENTITY_ALBUM, ENTITY_ARTIST, ENTITY_MOVIE,
    ENTITY_MUSIC_VIDEO, ENTITY_SERIES,
    ROLE_BACKDROP, ROLE_COVER, ROLE_POSTER, ROLE_THUMB,
)
from app.models.movie import Movie
from app.models.music import Album, Artist, MusicVideo, Track
from app.models.tv import Series
from app.models.user import User, UserRole
from app.services.security import hash_password


# Mirrors USERNAME_PATTERN in app.api.schemas. Kept inline so the CLI doesn't
# import pydantic just to validate one field.
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,64}$")


def cmd_create_admin(args: argparse.Namespace) -> int:
    username = args.username.strip().lower()
    name = args.name.strip()
    if not username or not name:
        print("username and name are required", file=sys.stderr)
        return 2
    if not _USERNAME_RE.match(username):
        print("username must be 3-64 chars: lowercase letters, digits, . _ -",
              file=sys.stderr)
        return 2

    # F7FIVE0_ADMIN_PASSWORD lets the installer seed the first admin without
    # putting the password on a command line.
    password = (
        args.password
        or os.environ.get("F7FIVE0_ADMIN_PASSWORD")
        or getpass.getpass("Password: ")
    )
    if len(password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        return 2

    # Role defaults to admin so the original `create-admin` behavior is
    # unchanged; pass --role member to seed a non-admin (e.g. a smoke-test user)
    # through the same supported path instead of hand-writing SQL.
    role_str = getattr(args, "role", "admin") or "admin"
    try:
        role = UserRole(role_str)
    except ValueError:
        print(f"invalid role '{role_str}' (use admin or member)", file=sys.stderr)
        return 2
    if role == UserRole.system:
        print("cannot create a system user", file=sys.stderr)
        return 2

    with db_session() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            print(f"user {username} already exists (role={existing.role.value})",
                  file=sys.stderr)
            return 1
        user = User(
            username=username,
            display_name=name,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        print(f"created {role.value} {username} id={user.id}")
    return 0


def cmd_backfill_genres(args: argparse.Namespace) -> int:
    """Walk every artist + album in the DB, pull `genres` from Lidarr by
    upstream id, and write the field onto the row.

    Idempotent: replaces whatever's there with the source-of-truth list.
    Skips rows missing a `lidarr_id` since there's nothing upstream to
    look up. Empty list when Lidarr returns no genres.
    """
    if not settings.lidarr_api_key:
        print("LIDARR_API_KEY not configured", file=sys.stderr)
        return 2

    # Local import so the CLI's other commands don't pay the httpx cost.
    from app.services.arr import LidarrClient
    from app.services.sync import _genres  # private helper; reuse so logic matches sync

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("backfill-genres")

    artists_touched = 0
    albums_touched = 0
    with db_session() as db, LidarrClient(
        settings.lidarr_url, settings.lidarr_api_key,
    ) as lc:
        for a in db.scalars(select(Artist)):
            if a.lidarr_id is None:
                continue
            try:
                payload = lc.get_artist(a.lidarr_id)
            except Exception:
                log.exception("artist %s lidarr fetch failed", a.id)
                continue
            a.genres = _genres(payload)
            artists_touched += 1
            try:
                albums = lc.list_albums(a.lidarr_id)
            except Exception:
                log.exception("artist %s lidarr albums fetch failed", a.id)
                albums = []
            albums_by_mbid: dict[str, dict] = {}
            albums_by_title: dict[str, dict] = {}
            for ap in albums:
                mbid = ap.get("foreignAlbumId")
                if mbid:
                    albums_by_mbid[mbid] = ap
                title = ap.get("title")
                if title:
                    albums_by_title.setdefault(title, ap)
            for alb in db.scalars(select(Album).where(Album.artist_id == a.id)):
                src = None
                if alb.mbid and alb.mbid in albums_by_mbid:
                    src = albums_by_mbid[alb.mbid]
                elif alb.title in albums_by_title:
                    src = albums_by_title[alb.title]
                if src is None:
                    continue
                alb.genres = _genres(src)
                albums_touched += 1
        log.info(
            "backfill-genres complete: artists=%d albums=%d",
            artists_touched, albums_touched,
        )
    return 0


def cmd_backfill_art(args: argparse.Namespace) -> int:
    """Walk every entity with an http-prefixed native image column and
    download the image into the art_overrides pipeline.

    Runs once after the 0017 migration so the library survives any *arr
    going offline. Idempotent: rows that already have an override are
    skipped. Rate-limited at settings.art_download_delay_ms between
    fetches so the *arr CDNs (and their upstream sources) don't throttle
    a long backfill.

    Entities with non-http native columns (e.g. Lidarr local-disk paths)
    are skipped here. They'll resolve on the next *arr sync if the
    upstream supplies a remoteUrl.
    """
    from app.services.art import (
        ArtValidationError, SYSTEM_USER_ID, fetch_and_save_url,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("backfill-art")

    delay_ms = max(0, int(settings.art_download_delay_ms))
    delay_sec = delay_ms / 1000.0

    # (model, native_column_attr, entity_kind, role, source_kind)
    targets: list[tuple[type, str, str, str, str]] = [
        (Artist, "image_path", ENTITY_ARTIST, ROLE_THUMB, "lidarr"),
        (Album, "cover_path", ENTITY_ALBUM, ROLE_COVER, "lidarr"),
        (Movie, "poster_path", ENTITY_MOVIE, ROLE_POSTER, "radarr"),
        (Movie, "backdrop_path", ENTITY_MOVIE, ROLE_BACKDROP, "radarr"),
        (Series, "poster_path", ENTITY_SERIES, ROLE_POSTER, "sonarr"),
        (Series, "backdrop_path", ENTITY_SERIES, ROLE_BACKDROP, "sonarr"),
        (MusicVideo, "thumb_path", ENTITY_MUSIC_VIDEO, ROLE_THUMB, "lidarr"),
    ]

    totals = {"ok": 0, "skipped": 0, "no_url": 0, "failed": 0}

    with db_session() as db:
        for model, col_attr, entity_kind, role, source_kind in targets:
            log.info("backfilling %s/%s from %s.%s ...",
                     entity_kind, role, model.__name__, col_attr)
            rows = list(db.scalars(select(model)))
            for row in rows:
                native = getattr(row, col_attr, None)
                if not native:
                    totals["no_url"] += 1
                    continue
                if not isinstance(native, str) or not native.lower().startswith(
                    ("http://", "https://"),
                ):
                    # Non-http path (e.g. Lidarr local MediaCover) is unusable.
                    totals["skipped"] += 1
                    continue
                existing = db.get(ArtOverride, (entity_kind, row.id, role))
                if existing is not None:
                    totals["skipped"] += 1
                    continue
                try:
                    fetch_and_save_url(
                        db,
                        entity_kind=entity_kind,
                        entity_id=row.id,
                        role=role,
                        url=native,
                        set_by_user_id=SYSTEM_USER_ID,
                        source_kind=source_kind,
                    )
                except ArtValidationError as exc:
                    log.warning(
                        "%s/%s id=%s url=%s failed: %s",
                        entity_kind, role, row.id, native, exc,
                    )
                    totals["failed"] += 1
                    continue
                totals["ok"] += 1
                db.commit()
                if delay_sec > 0:
                    time.sleep(delay_sec)
            log.info("  done %s/%s", entity_kind, role)

    log.info("backfill-art complete: %s", totals)
    return 0


def cmd_scan_art(args: argparse.Namespace) -> int:
    """Find artists and albums without art overrides and bulk-download
    images from external sources (AudioDB for artists, iTunes for albums).

    Skips any entity that already has an override row. Rate-limited at
    settings.art_download_delay_ms between fetches. Logs every hit/miss
    so the admin can see which artists are still uncovered.
    """
    from app.services.art import (
        ArtValidationError, SYSTEM_USER_ID, fetch_and_save_url,
    )
    from app.services.art_sources import audiodb as audiodb_source
    from app.services.art_sources import itunes as itunes_source

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("scan-art")

    delay_sec = max(0, settings.art_download_delay_ms) / 1000.0
    counts = {"ok": 0, "skip": 0, "miss": 0, "fail": 0}

    kind = args.kind

    with db_session() as db:
        # --- Artists ---
        if kind in ("artist", "all"):
            artists = list(db.scalars(select(Artist)))
            log.info("scanning %d artists for missing art ...", len(artists))
            for a in artists:
                existing = db.get(ArtOverride, (ENTITY_ARTIST, a.id, ROLE_THUMB))
                if existing is not None:
                    counts["skip"] += 1
                    continue
                # Try AudioDB first (real artist portraits).
                candidates = []
                if settings.audiodb_api_key and a.name:
                    candidates = audiodb_source.search_artist(
                        settings.audiodb_api_key, a.name,
                    )
                # Fall back to iTunes album art as a proxy.
                if not candidates and a.name:
                    candidates = itunes_source.search_artist(a.name)
                if not candidates:
                    log.info("  miss: %s", a.name)
                    counts["miss"] += 1
                    continue
                url = candidates[0]["url"]
                try:
                    fetch_and_save_url(
                        db,
                        entity_kind=ENTITY_ARTIST,
                        entity_id=a.id,
                        role=ROLE_THUMB,
                        url=url,
                        set_by_user_id=SYSTEM_USER_ID,
                        source_kind=candidates[0].get("source", "url"),
                    )
                    db.commit()
                    log.info("  ok: %s <- %s", a.name, candidates[0].get("source"))
                    counts["ok"] += 1
                except ArtValidationError as exc:
                    log.warning("  fail: %s url=%s reason=%s", a.name, url, exc)
                    counts["fail"] += 1
                if delay_sec > 0:
                    time.sleep(delay_sec)

        # --- Albums ---
        if kind in ("album", "all"):
            albums = list(db.scalars(select(Album)))
            log.info("scanning %d albums for missing art ...", len(albums))
            for alb in albums:
                existing = db.get(ArtOverride, (ENTITY_ALBUM, alb.id, ROLE_COVER))
                if existing is not None:
                    counts["skip"] += 1
                    continue
                # Look up the parent artist name for the search query.
                artist = db.get(Artist, alb.artist_id)
                artist_name = artist.name if artist else None
                search_term = f"{artist_name} {alb.title}" if artist_name else alb.title
                candidates = itunes_source.search_artist(search_term) if search_term else []
                if not candidates:
                    log.info("  miss: %s - %s", artist_name or "?", alb.title)
                    counts["miss"] += 1
                    continue
                url = candidates[0]["url"]
                try:
                    fetch_and_save_url(
                        db,
                        entity_kind=ENTITY_ALBUM,
                        entity_id=alb.id,
                        role=ROLE_COVER,
                        url=url,
                        set_by_user_id=SYSTEM_USER_ID,
                        source_kind="itunes",
                    )
                    db.commit()
                    log.info("  ok: %s - %s <- itunes", artist_name or "?", alb.title)
                    counts["ok"] += 1
                except ArtValidationError as exc:
                    log.warning(
                        "  fail: %s - %s url=%s reason=%s",
                        artist_name or "?", alb.title, url, exc,
                    )
                    counts["fail"] += 1
                if delay_sec > 0:
                    time.sleep(delay_sec)

    log.info("scan-art complete: %s", counts)
    return 0


def cmd_enrich_metadata(args: argparse.Namespace) -> int:
    """Walk movies, artists, and/or albums and run the metadata-enrichment
    pipeline against each. Hits TMDB for movies, MusicBrainz + Wikipedia
    for music. Idempotent: rows whose `metadata_synced_at` is fresher
    than `METADATA_TTL_DAYS` are skipped unless `--force` is set.
    """
    from app.services.metadata.runner import (
        enrich_album, enrich_artist, enrich_movie,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("enrich-metadata")

    if args.kind == "all":
        kinds: list[str] = ["movie", "artist", "album"]
    else:
        kinds = [args.kind]

    handlers: dict[str, tuple] = {
        "movie": (Movie, enrich_movie),
        "artist": (Artist, enrich_artist),
        "album": (Album, enrich_album),
    }

    with db_session() as db:
        for kind in kinds:
            model, fn = handlers[kind]
            stmt = select(model.id).order_by(model.id)
            if args.limit:
                stmt = stmt.limit(args.limit)
            ids = list(db.scalars(stmt))
            log.info("enriching %d %s rows (force=%s)", len(ids), kind, args.force)

            counts: dict[str, int] = {
                "ok": 0, "skipped": 0, "no_external_id": 0, "failed": 0,
            }
            for i, eid in enumerate(ids, start=1):
                result = fn(db, eid, force=args.force)
                counts[result.status] = counts.get(result.status, 0) + 1
                if i % 50 == 0:
                    log.info("  %s %d/%d %s", kind, i, len(ids), counts)
            log.info("done %s: %s", kind, counts)
    return 0


def cmd_analyze_audio(args: argparse.Namespace) -> int:
    """Compute loudness, waveform, gain, and similarity for tracks.

    Runs OUT OF BAND from the API: one file at a time (throttled), resumable
    (skips tracks whose analysis row is already stamped `analyzed_at` unless
    `--force`), and low-priority (each ffmpeg pass is a subprocess; a short
    sleep between files keeps the box responsive during a long backfill). It
    never touches the API process.

    Two phases:
      1. Per-track loudness + waveform + gain -> track_audio_analysis rows.
      2. Similarity edges (top-N per track) from the derived features.

    Album gain is computed after phase 1 per album (needs every track's LUFS).
    """
    import time as _time

    from app.models.audio_analysis import (
        ANALYSIS_VERSION, TrackAudioAnalysis, TrackSimilarity,
    )
    from app.models.media_file import MediaFile, MediaKind, ScanState
    from app.services import audio_analysis as aa
    from app.services import path_map

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("analyze-audio")

    target_lufs = float(getattr(args, "target_lufs", aa.TARGET_LUFS))
    allow_boost = bool(getattr(args, "allow_boost", False))
    throttle_sec = max(0.0, float(getattr(args, "throttle", 0.5)))
    force = bool(getattr(args, "force", False))

    counts = {"analyzed": 0, "skipped": 0, "no_file": 0, "failed": 0}

    with db_session() as db:
        # Build the track working set.
        stmt = select(Track.id).order_by(Track.id)
        if getattr(args, "track_id", None):
            stmt = select(Track.id).where(Track.id == args.track_id)
        elif args.limit:
            stmt = stmt.limit(args.limit)
        track_ids = list(db.scalars(stmt))
        log.info("analyze-audio: %d track(s) in working set (force=%s)",
                 len(track_ids), force)

        # ---- Phase 1: per-track loudness + waveform + track gain ----
        analyzed_this_run: list[uuid.UUID] = []
        for i, tid in enumerate(track_ids, start=1):
            row = db.scalar(
                select(TrackAudioAnalysis).where(TrackAudioAnalysis.track_id == tid)
            )
            if row is not None and row.analyzed_at is not None and not force:
                counts["skipped"] += 1
                continue

            mf = db.scalar(
                select(MediaFile)
                .where(
                    MediaFile.kind == MediaKind.track,
                    MediaFile.ref_id == tid,
                    MediaFile.scan_state == ScanState.ready,
                )
                .order_by(MediaFile.id)
                .limit(1)
            )
            if mf is None:
                counts["no_file"] += 1
                continue

            path = path_map.translate(mf.path) or mf.path
            lufs = aa.measure_loudness(path)
            peaks = aa.compute_waveform(path)
            if lufs is None and peaks is None:
                counts["failed"] += 1
                log.warning("  track %s: analysis produced nothing (%s)", tid, path)
                continue

            gain = aa.compute_gain_db(lufs, target_lufs=target_lufs, allow_boost=allow_boost)
            if row is None:
                row = TrackAudioAnalysis(track_id=tid)
                db.add(row)
            row.media_file_id = mf.id
            row.integrated_lufs = lufs
            row.track_gain_db = gain
            row.waveform_peaks = peaks
            row.analysis_version = ANALYSIS_VERSION
            row.analyzed_at = datetime.now(timezone.utc)
            db.flush()
            counts["analyzed"] += 1
            analyzed_this_run.append(tid)

            if i % 25 == 0:
                log.info("  progress %d/%d %s", i, len(track_ids), counts)
                db.commit()
            if throttle_sec > 0:
                _time.sleep(throttle_sec)
        db.commit()

        # ---- Album gain: target the album's integrated loudness ----
        # Album gain normalizes each album to the same reference (target LUFS)
        # using the album's own integrated loudness (mean of its tracks' LUFS as
        # a cheap stand-in for a true album measurement), so intra-album
        # dynamics are preserved. Recomputed for every album touched this run.
        touched_albums: set[uuid.UUID] = set()
        for tid in analyzed_this_run:
            t = db.get(Track, tid)
            if t is not None:
                touched_albums.add(t.album_id)
        for album_id in touched_albums:
            album_track_ids = list(db.scalars(
                select(Track.id).where(Track.album_id == album_id)
            ))
            rows = list(db.scalars(
                select(TrackAudioAnalysis)
                .where(TrackAudioAnalysis.track_id.in_(album_track_ids))
            ))
            lufs_vals = [r.integrated_lufs for r in rows if r.integrated_lufs is not None]
            if not lufs_vals:
                continue
            album_lufs = sum(lufs_vals) / len(lufs_vals)
            album_gain = aa.compute_gain_db(
                album_lufs, target_lufs=target_lufs, allow_boost=allow_boost,
            )
            for r in rows:
                r.album_gain_db = album_gain
        db.commit()

        # ---- Phase 2: similarity edges (top-N per track) ----
        top_n = int(getattr(args, "similar_top_n", 25))
        # Build feature vectors for every analyzed track in the library so the
        # graph is complete, not just this run's slice.
        all_rows = list(db.scalars(
            select(TrackAudioAnalysis).where(TrackAudioAnalysis.analyzed_at.isnot(None))
        ))
        feats: list[tuple[uuid.UUID, aa.AudioFeatures]] = []
        for r in all_rows:
            fv = aa.features_from_waveform(r.waveform_peaks or [], r.integrated_lufs)
            feats.append((r.track_id, fv))

        if len(feats) >= 2 and (force or analyzed_this_run):
            # Recompute edges only for tracks analyzed this run (or all, on
            # --force) to keep an incremental run cheap.
            seeds = set(analyzed_this_run) if not force else {t for t, _ in feats}
            for seed_id, seed_fv in feats:
                if seed_id not in seeds:
                    continue
                scored = [
                    (other_id, aa.similarity_score(seed_fv, other_fv))
                    for other_id, other_fv in feats
                    if other_id != seed_id
                ]
                scored.sort(key=lambda p: p[1], reverse=True)
                top = scored[:top_n]
                # Replace this seed's edges.
                db.query(TrackSimilarity).filter(
                    TrackSimilarity.track_id == seed_id
                ).delete(synchronize_session=False)
                for other_id, score in top:
                    db.add(TrackSimilarity(
                        track_id=seed_id, similar_track_id=other_id, score=score,
                    ))
            db.commit()
            log.info("similarity graph updated for %d seed track(s)", len(seeds))

    log.info("analyze-audio complete: %s", counts)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="f7five0")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create-admin", help="Create a user (admin by default)")
    p.add_argument("--username", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--password", help="Password (prompted if omitted)")
    p.add_argument("--role", default="admin", choices=["admin", "member"],
                   help="User role (default: admin)")
    p.set_defaults(func=cmd_create_admin)

    p2 = sub.add_parser(
        "backfill-genres",
        help="Refresh artists.genres and albums.genres from Lidarr",
    )
    p2.set_defaults(func=cmd_backfill_genres)

    p_bart = sub.add_parser(
        "backfill-art",
        help="Download existing remote image URLs into the art_overrides pipeline",
    )
    p_bart.set_defaults(func=cmd_backfill_art)

    p_scan = sub.add_parser(
        "scan-art",
        help="Bulk-search AudioDB/iTunes for missing artist and album art",
    )
    p_scan.add_argument(
        "--kind", choices=("artist", "album", "all"), default="all",
    )
    p_scan.set_defaults(func=cmd_scan_art)

    p3 = sub.add_parser(
        "enrich-metadata",
        help="Run TMDB / MusicBrainz / Wikipedia enrichment over the library",
    )
    p3.add_argument(
        "--kind", choices=("movie", "artist", "album", "all"), default="all",
    )
    p3.add_argument(
        "--force", action="store_true",
        help="Re-enrich even if metadata_synced_at is within TTL",
    )
    p3.add_argument(
        "--limit", type=int, default=0,
        help="Only process the first N rows (0 = no limit)",
    )
    p3.set_defaults(func=cmd_enrich_metadata)

    p4 = sub.add_parser(
        "analyze-audio",
        help="Compute loudness, waveform, gain, and similarity for tracks",
    )
    p4.add_argument(
        "--limit", type=int, default=0,
        help="Only process the first N tracks (0 = no limit)",
    )
    p4.add_argument(
        "--track-id", type=uuid.UUID, default=None,
        help="Analyze a single track by id (overrides --limit)",
    )
    p4.add_argument(
        "--force", action="store_true",
        help="Re-analyze tracks whose analyzed_at is already set",
    )
    p4.add_argument(
        "--throttle", type=float, default=0.5,
        help="Seconds to sleep between files (default 0.5; low-priority backfill)",
    )
    p4.add_argument(
        "--target-lufs", type=float, default=-16.0,
        help="Loudness normalization target in LUFS (default -16)",
    )
    p4.add_argument(
        "--allow-boost", action="store_true",
        help="Allow positive gain (boost quiet tracks); default is attenuation-only",
    )
    p4.add_argument(
        "--similar-top-n", type=int, default=25,
        help="Number of similarity edges to keep per track (default 25)",
    )
    p4.set_defaults(func=cmd_analyze_audio)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
