"""Refresh podcast feeds: conditional GET, upsert by guid, auto-download.

`refresh_podcast` fetches one show's feed through the guard, parses it and
upserts its episodes. A failed fetch keeps the old episodes and records
`last_error`. `refresh_all` does that for every show somebody follows and
reports through `scan_status` (`podcast_refresh_status`), saving as it goes the
same way the folder scan does.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.art import ArtOverride, ENTITY_PODCAST, ROLE_COVER
from app.models.podcast import (
    SOURCE_FEED, Podcast, PodcastEpisode, PodcastSubscription,
)
from app.services import net_guard, scan_status
from app.services.podcasts import feed as feed_service

log = logging.getLogger("f7five0.podcasts.refresh")

SOURCE_KIND_FEED = "feed"
MAX_GUID_CHARS = 1000

QueueDownload = Callable[[uuid.UUID], object]


class SubscribeError(Exception):
    """Adding a feed failed. `code` is what the API answers with."""

    def __init__(self, code: str, status_code: int, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code


@dataclass
class RefreshOutcome:
    status: str  # "updated" | "not_modified" | "error"
    new_episode_ids: list = field(default_factory=list)
    error: Optional[str] = None
    # "blocked" (the guard refused the address), "unreachable", "invalid" (not a feed)
    error_kind: Optional[str] = None


@dataclass
class RefreshStats:
    shows: int = 0
    new_episodes: int = 0
    errors: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def episode_key(parsed: feed_service.ParsedEpisode) -> Optional[str]:
    """The identity of an episode in its show: the feed's guid, else the
    enclosure URL. A very long one is hashed to fit the column and its unique
    index."""
    key = (parsed.guid or parsed.enclosure_url or "").strip()
    if not key:
        return None
    if len(key) > MAX_GUID_CHARS:
        key = "sha1:" + hashlib.sha1(key.encode("utf-8")).hexdigest()
    return key


def sync_art(db: Session, pod: Podcast, art_url: Optional[str]) -> None:
    """Fetch the show's picture into the art pipeline (through the guard). Art an
    admin set, or the scanner imported from a folder, is left alone; only a
    picture this refresh saved earlier is replaced when the feed's URL changes."""
    if not art_url:
        return
    from app.services import art as art_service

    existing = db.get(ArtOverride, (ENTITY_PODCAST, pod.id, ROLE_COVER))
    if existing is not None and (existing.source_kind != SOURCE_KIND_FEED or existing.source_ref == art_url):
        return
    try:
        art_service.fetch_and_save_url(
            db, entity_kind=ENTITY_PODCAST, entity_id=pod.id, role=ROLE_COVER, url=art_url,
            set_by_user_id=art_service.SYSTEM_USER_ID, source_kind=SOURCE_KIND_FEED,
        )
    except art_service.ArtValidationError as exc:
        log.warning("podcast art skipped for %s: %s", pod.id, exc)


def _apply_feed(db: Session, pod: Podcast, parsed: feed_service.ParsedFeed) -> list[PodcastEpisode]:
    """Write the parsed show and upsert its episodes. Returns the new ones."""
    pod.title = parsed.title[:512]
    pod.author = (parsed.author or None) and parsed.author[:512]
    pod.description = parsed.description or None
    if parsed.podcast_guid:
        pod.podcast_guid = parsed.podcast_guid[:128]

    existing = {
        e.guid: e for e in db.scalars(select(PodcastEpisode).where(PodcastEpisode.podcast_id == pod.id))
    }
    created: list[PodcastEpisode] = []
    for parsed_ep in parsed.episodes:
        key = episode_key(parsed_ep)
        if key is None:
            continue
        ep = existing.get(key)
        if ep is None:
            ep = PodcastEpisode(id=uuid.uuid4(), podcast_id=pod.id, guid=key, title="")
            db.add(ep)
            existing[key] = ep
            created.append(ep)
        ep.title = parsed_ep.title[:1024]
        ep.description = parsed_ep.description or None
        ep.published_at = parsed_ep.published_at
        ep.duration_sec = parsed_ep.duration_sec or ep.duration_sec
        ep.enclosure_url = parsed_ep.enclosure_url[:2048]
        ep.enclosure_type = (parsed_ep.enclosure_type or None) and parsed_ep.enclosure_type[:128]
        ep.enclosure_length = parsed_ep.enclosure_length
        ep.season = parsed_ep.season
        ep.episode = parsed_ep.episode
        if ep.chapters_url != parsed_ep.chapters_url:
            ep.chapters_url = parsed_ep.chapters_url
            ep.chapters_json = None  # the cached copy belonged to the old URL
    db.flush()
    return created


def _auto_download_ids(db: Session, pod: Podcast, created: Iterable[PodcastEpisode]) -> list[uuid.UUID]:
    """Episodes to queue a server download for: new, published after the
    subscription that wants them, and audio."""
    subs = db.scalars(select(PodcastSubscription).where(
        PodcastSubscription.podcast_id == pod.id, PodcastSubscription.auto_download.is_(True),
    )).all()
    if not subs:
        return []
    cutoffs = [_aware(s.created_at) for s in subs if s.created_at is not None]
    ids: list[uuid.UUID] = []
    for ep in created:
        published = _aware(ep.published_at)
        if published is None or (ep.enclosure_type or "").startswith("video/"):
            continue
        if any(published > cutoff for cutoff in cutoffs):
            ids.append(ep.id)
    return ids


def _short(exc: Exception) -> str:
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0][:300]


def refresh_podcast(
    db: Session, pod: Podcast, *, queue_download: Optional[QueueDownload] = None,
    now: Optional[datetime] = None,
) -> RefreshOutcome:
    """Refresh one show from its feed. Does not commit."""
    now = now or _now()
    headers = {"Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"}
    if pod.etag:
        headers["If-None-Match"] = pod.etag
    if pod.last_modified:
        headers["If-Modified-Since"] = pod.last_modified
    if not pod.feed_url:
        return RefreshOutcome("error", error="this show has no feed", error_kind="invalid")
    try:
        fetched = net_guard.fetch_bytes(pod.feed_url, max_bytes=net_guard.FEED_MAX_BYTES, headers=headers)
        if fetched.status == 304:
            pod.last_checked_at = now
            pod.last_error = None
            return RefreshOutcome("not_modified")
        parsed = feed_service.parse_feed(fetched.body, pod.feed_url)
    except net_guard.NetGuardError as exc:
        pod.last_checked_at, pod.last_error = now, _short(exc)
        return RefreshOutcome("error", error=pod.last_error,
                              error_kind="blocked" if exc.status_code == 400 else "unreachable")
    except feed_service.FeedError as exc:
        pod.last_checked_at, pod.last_error = now, _short(exc)
        return RefreshOutcome("error", error=pod.last_error, error_kind="invalid")

    created = _apply_feed(db, pod, parsed)
    pod.etag = (fetched.headers.get("etag") or None)
    pod.last_modified = (fetched.headers.get("last-modified") or None)
    pod.last_checked_at = now
    pod.last_error = None
    db.flush()
    sync_art(db, pod, parsed.art_url)
    if queue_download is not None:
        for episode_id in _auto_download_ids(db, pod, created):
            try:
                queue_download(episode_id)
            except Exception:  # noqa: BLE001  (a queue hiccup must not undo the refresh)
                log.exception("could not queue the download of episode %s", episode_id)
    return RefreshOutcome("updated", new_episode_ids=[e.id for e in created])


def refresh_all(
    db: Session, *, queue_download: Optional[QueueDownload] = None,
    only_ids: Optional[Iterable[uuid.UUID]] = None,
) -> RefreshStats:
    """Refresh every show with at least one subscriber (or just `only_ids`),
    saving and reporting status after each show. `queue_download` is called with
    the id of each episode that should download to the server by itself."""
    scan_status.pr_begin(db, force=True)
    db.commit()

    stats = RefreshStats()
    last_error: Optional[str] = None
    try:
        q = select(Podcast).where(Podcast.feed_url.is_not(None), Podcast.source == SOURCE_FEED)
        if only_ids is not None:
            q = q.where(Podcast.id.in_(list(only_ids)))
        else:
            q = q.where(Podcast.id.in_(select(PodcastSubscription.podcast_id)))
        shows = db.scalars(q.order_by(Podcast.created_at)).all()
        total = len(shows)
        scan_status.pr_progress(db, total=total, count=0, added=0, errors=0)
        db.commit()
        done = 0
        for pod in shows:
            try:
                out = refresh_podcast(db, pod, queue_download=queue_download)
            except Exception as exc:  # noqa: BLE001
                log.exception("refreshing %s raised", pod.id)
                db.rollback()
                stats.errors += 1
                last_error = _short(exc)
            else:
                stats.shows += 1
                stats.new_episodes += len(out.new_episode_ids)
                if out.status == "error":
                    stats.errors += 1
                    last_error = out.error
            done += 1
            scan_status.pr_progress(
                db, total=total, count=done, added=stats.new_episodes, errors=stats.errors,
                error=last_error,
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("podcast refresh failed")
        db.rollback()
        scan_status.pr_finish(db, f"The refresh stopped: {_short(exc)}")
        db.commit()
        return stats
    scan_status.pr_finish(db, last_error if stats.errors else None)
    db.commit()
    return stats


# ---------------------------------------------------------------------------
# Adding shows
# ---------------------------------------------------------------------------
def normalize_feed_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url.lower().startswith(("http://", "https://")) or len(url) > 2048:
        raise SubscribeError("bad_feed_url", 422, "the feed address must be a full http or https URL")
    return url


def get_or_create_show(db: Session, feed_url: str) -> tuple[Podcast, bool]:
    """The show for this feed, fetching and parsing the feed first when it is
    new. Raises SubscribeError and leaves nothing behind when the feed cannot
    be read. Does not commit."""
    url = normalize_feed_url(feed_url)
    pod = db.scalar(select(Podcast).where(Podcast.feed_url == url))
    if pod is not None:
        return pod, False
    pod = Podcast(id=uuid.uuid4(), feed_url=url, title=url[:512], source=SOURCE_FEED)
    db.add(pod)
    db.flush()
    out = refresh_podcast(db, pod)
    if out.status == "error":
        db.delete(pod)
        db.flush()
        if out.error_kind == "blocked":
            raise SubscribeError("feed_blocked", 400, out.error or "")
        if out.error_kind == "invalid":
            raise SubscribeError("feed_invalid", 422, out.error or "")
        raise SubscribeError("feed_unreachable", 502, out.error or "")
    return pod, True


def add_placeholder_show(db: Session, feed_url: str) -> tuple[Podcast, bool]:
    """A show known only by its feed URL (an OPML import). It is fetched later
    in the background. Does not commit."""
    url = normalize_feed_url(feed_url)
    pod = db.scalar(select(Podcast).where(Podcast.feed_url == url))
    if pod is not None:
        return pod, False
    pod = Podcast(id=uuid.uuid4(), feed_url=url, title=url[:512], source=SOURCE_FEED)
    db.add(pod)
    db.flush()
    return pod, True
