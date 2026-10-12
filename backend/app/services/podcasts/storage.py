"""Podcast storage: what server downloads use, and how much room is left.

There is no cap on downloads (decision 2026-10-11). Instead Admin shows what
the downloaded files add up to and the free space on the drive of each podcasts
library folder, and a reminder banner appears when free space drops below
PODCAST_FREE_SPACE_WARN_GB (10 by default).
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.media_file import MediaFile
from app.models.podcast import PodcastEpisode
from app.services import library_folders

GB = 1024 ** 3


def disk_free(path: str) -> tuple[int, int]:
    """(free bytes, total bytes) of the drive or share that holds `path`."""
    usage = shutil.disk_usage(path)
    return usage.free, usage.total


def downloaded_bytes(db: Session) -> int:
    """The sum of the sizes of the files F7FIVE0 downloaded."""
    total = db.scalar(
        select(func.coalesce(func.sum(MediaFile.size_bytes), 0))
        .join(PodcastEpisode, PodcastEpisode.media_file_id == MediaFile.id)
        .where(PodcastEpisode.downloaded_by_f7five0.is_(True))
    )
    return int(total or 0)


def _folder_entry(path: str) -> dict:
    entry: dict = {"path": path, "reachable": False, "free_bytes": None, "total_bytes": None}
    try:
        if os.path.isdir(path):
            free, total = disk_free(path)
            entry.update(reachable=True, free_bytes=int(free), total_bytes=int(total))
    except OSError:
        pass
    return entry


def usage(db: Session) -> dict:
    """{used_bytes, warn_gb, low_space, folders: [{path, reachable, free_bytes,
    total_bytes}]} for Admin."""
    warn_gb = int(settings.podcast_free_space_warn_gb)
    folders = [_folder_entry(p) for p in library_folders.folders(db, "podcasts") if p]
    low = any(
        f["reachable"] and f["free_bytes"] is not None and f["free_bytes"] < warn_gb * GB
        for f in folders
    )
    return {
        "used_bytes": downloaded_bytes(db),
        "warn_gb": warn_gb,
        "low_space": low,
        "folders": folders,
    }


def is_low(db: Session) -> bool:
    return bool(usage(db)["low_space"])
