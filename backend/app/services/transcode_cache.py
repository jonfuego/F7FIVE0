r"""Transcode segment cache: accounting + LRU eviction.

Disk layout (same as transcoder.py):
    {transcode_cache_dir}\{media_file_id}\{variant}\t{offset_bucket}\
        index.m3u8
        seg_NNNNN.ts

One "cache entry" is a `{media_file_id}/{variant}/t{offset_bucket}`
directory. Eviction deletes whole entries (one bucket of one variant),
not individual segments. The `transcode_cache` table mirrors disk so a
`last_access_at` write from segment serving, plus scheduled walk from
the janitor, keep the DB in sync.
"""
from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import db_session
from app.models.transcode import TranscodeCache


log = logging.getLogger("f7five0.transcode_cache")


@dataclass
class CacheEntry:
    media_file_id: uuid.UUID
    variant: str
    offset_bucket: int
    path: Path
    size_bytes: int
    segment_count: int
    last_access_at: datetime


# Cache bucket dirs look like "t0", "t2710", etc. Anything that doesn't
# parse is treated as a stray dir and skipped — the janitor doesn't want
# to account for directories it didn't create.
_BUCKET_DIR_RE = re.compile(r"^t(\d+)$")


def _cache_root() -> Path:
    return Path(settings.transcode_cache_dir)


def _iter_entries() -> list[CacheEntry]:
    """Walk the cache dir. Skip directories that don't look like UUIDs.

    Each {media_file_id}/{variant}/t{offset_bucket} triple becomes one
    entry. Size and last-access are computed from file stats so we don't
    depend on per-segment DB updates.
    """
    root = _cache_root()
    if not root.exists():
        return []

    entries: list[CacheEntry] = []
    for mid_dir in root.iterdir():
        if not mid_dir.is_dir():
            continue
        try:
            mid = uuid.UUID(mid_dir.name)
        except ValueError:
            continue
        for var_dir in mid_dir.iterdir():
            if not var_dir.is_dir():
                continue
            for bucket_dir in var_dir.iterdir():
                if not bucket_dir.is_dir():
                    continue
                m = _BUCKET_DIR_RE.match(bucket_dir.name)
                if not m:
                    continue
                bucket = int(m.group(1))
                size = 0
                segs = 0
                newest_mtime = 0.0
                for f in bucket_dir.iterdir():
                    if not f.is_file():
                        continue
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    size += st.st_size
                    if f.suffix == ".ts":
                        segs += 1
                    if st.st_mtime > newest_mtime:
                        newest_mtime = st.st_mtime
                if size == 0 and segs == 0:
                    continue
                entries.append(CacheEntry(
                    media_file_id=mid,
                    variant=var_dir.name,
                    offset_bucket=bucket,
                    path=bucket_dir,
                    size_bytes=size,
                    segment_count=segs,
                    last_access_at=datetime.fromtimestamp(
                        newest_mtime or time.time(), tz=timezone.utc,
                    ),
                ))
    return entries


def total_size_bytes() -> int:
    return sum(e.size_bytes for e in _iter_entries())


def _upsert_cache_rows(db: Session, entries: list[CacheEntry]) -> None:
    """Mirror disk state into transcode_cache. Drops rows for dirs we deleted."""
    existing = {
        (c.media_file_id, c.variant, c.offset_bucket): c
        for c in db.scalars(select(TranscodeCache))
    }
    seen: set[tuple[uuid.UUID, str, int]] = set()

    for e in entries:
        key = (e.media_file_id, e.variant, e.offset_bucket)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            db.add(TranscodeCache(
                media_file_id=e.media_file_id,
                variant=e.variant,
                offset_bucket=e.offset_bucket,
                segment_count=e.segment_count,
                size_bytes=e.size_bytes,
                last_access_at=e.last_access_at,
            ))
        else:
            row.segment_count = e.segment_count
            row.size_bytes = e.size_bytes
            # Don't regress last_access_at if DB is newer than disk mtime
            # (segment handler could also be updating it in the future).
            if e.last_access_at > row.last_access_at:
                row.last_access_at = e.last_access_at

    # Drop rows whose dirs are gone.
    for key, row in existing.items():
        if key not in seen:
            db.delete(row)


def _delete_entry(entry: CacheEntry) -> None:
    try:
        shutil.rmtree(entry.path, ignore_errors=False)
        log.info("evicted cache %s/%s/t%s (%.1f MB)",
                 entry.media_file_id, entry.variant, entry.offset_bucket,
                 entry.size_bytes / 1_048_576)
    except Exception:
        log.exception("failed to evict %s", entry.path)


def enforce_cap(cap_bytes: int | None = None) -> int:
    """Evict oldest entries until total size is below cap. Returns bytes freed.

    Safe to run concurrently with transcoder janitor (both hold their own
    locks; we operate on separate rows). Will not delete a directory that
    currently holds an active job because the job is keeping its mtime
    fresh via touch() on every segment fetch.
    """
    if cap_bytes is None:
        cap_bytes = settings.transcode_cache_max_gb * (1024 ** 3)

    entries = _iter_entries()
    total = sum(e.size_bytes for e in entries)
    log.info("cache size %.1f GB / cap %.1f GB (%d entries)",
             total / 1_073_741_824, cap_bytes / 1_073_741_824, len(entries))

    freed = 0
    if total > cap_bytes:
        # Oldest first
        entries.sort(key=lambda e: e.last_access_at)
        for e in entries:
            if total - freed <= cap_bytes:
                break
            _delete_entry(e)
            freed += e.size_bytes

    # Whether we evicted or not, mirror current disk into the DB so queries
    # see fresh stats.
    try:
        with db_session() as db:
            # Re-walk after possible evictions so DB reflects final state.
            _upsert_cache_rows(db, _iter_entries())
    except Exception:
        log.exception("failed to upsert transcode_cache rows")

    return freed
