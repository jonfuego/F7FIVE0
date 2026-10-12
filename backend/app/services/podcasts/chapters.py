"""Chapters for an episode.

In order of preference:

1. the Podcasting 2.0 `podcast:chapters` JSON the feed links to, fetched
   through the guard (2 MB cap) and cached in `chapters_json`;
2. the chapters inside the file, when the episode has one on the server
   (ffprobe);
3. nothing.

Everything a feed can put in a chapter is untrusted: titles become plain text,
and `img` / `url` are kept only when they are http(s) addresses, so a
`javascript:` or `data:` link can never reach a page.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.media_file import MediaFile
from app.models.podcast import PodcastEpisode
from app.services import ffprobe, media_paths, net_guard
from app.services.podcasts import feed as feed_service

log = logging.getLogger("f7five0.podcasts.chapters")

MAX_CHAPTERS = 500
MAX_TITLE_CHARS = 200


def _http(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.lower().startswith(("http://", "https://")) and len(value) <= 2048 else None


def _clean(raw: Any, index: int) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    if raw.get("toc") is False:  # a chapter the publisher marks as not for the list
        return None
    start = raw.get("startTime", raw.get("start_sec"))
    try:
        start = float(start)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(start) or start < 0:
        return None
    title = " ".join(feed_service.plain_text(raw.get("title"), limit=MAX_TITLE_CHARS).split())
    out: dict = {"start_sec": round(start, 3), "title": title or f"Chapter {index + 1}"}
    img, url = _http(raw.get("img")), _http(raw.get("url"))
    if img:
        out["img"] = img
    if url:
        out["url"] = url
    return out


def normalize(items: Any) -> list[dict]:
    """A list of raw chapters (Podcasting 2.0 JSON items, or our own stored
    ones) to `[{start_sec, title, img?, url?}]`, sorted, capped."""
    if not isinstance(items, list):
        return []
    cleaned = [c for c in (_clean(raw, i) for i, raw in enumerate(items)) if c is not None]
    cleaned.sort(key=lambda c: c["start_sec"])
    return cleaned[:MAX_CHAPTERS]


def parse_chapters_json(body: bytes) -> list[dict]:
    try:
        data = json.loads(body.decode("utf-8-sig", errors="replace"))
    except ValueError:
        return []
    items = data.get("chapters") if isinstance(data, dict) else data
    return normalize(items)


def get_chapters(db: Session, episode: PodcastEpisode) -> list[dict]:
    """The episode's chapters. Caches a feed's chapters on the episode (the
    caller commits). Never raises: a chapters file that cannot be fetched or
    read just means the next source is tried."""
    if episode.chapters_json is not None:
        return normalize(episode.chapters_json)

    if episode.chapters_url:
        try:
            fetched = net_guard.fetch_bytes(
                episode.chapters_url, max_bytes=net_guard.CHAPTERS_MAX_BYTES,
                headers={"Accept": "application/json+chapters, application/json;q=0.9, */*;q=0.5"},
            )
        except net_guard.NetGuardError as exc:
            log.info("chapters for episode %s not fetched: %s", episode.id, exc)
        else:
            chapters = parse_chapters_json(fetched.body)
            if chapters:
                episode.chapters_json = chapters
                db.flush()
                return chapters

    if episode.media_file_id:
        mf = db.get(MediaFile, episode.media_file_id)
        if mf is not None and mf.path and media_paths.is_contained(db, mf.path):
            return normalize(ffprobe.probe_chapters(mf.path))
    return []
