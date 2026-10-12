"""Podcasts for signed-in users: search, subscribe, progress, chapters, downloads.

Every route needs a signed-in user (`current_user`); the Admin routes (storage,
refresh, removing a server download, the Podcast Index key) live in
`api/admin.py` behind `require_admin`. The web reaches these through the library
BFF (`/api/library/podcasts/...` -> `/api/podcasts/...`); the app calls them
directly with its Bearer token.

Subscriptions and progress belong to the caller: nothing here reads another
user's rows. Static paths (`/search`, `/opml`, `/subscribe`, `/episodes/...`) are
declared before the `/{id}` routes so they are never read as a show id.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Iterable, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import scheduler
from app.api.deps import current_user, get_db
from app.api.schemas import (
    PodcastDetailOut, PodcastEpisodeOut, PodcastHomeOut, PodcastOpmlResultOut, PodcastOut,
    PodcastSearchOut, PodcastSearchResultOut, PodcastSubscribeIn, PodcastSubscriptionOut,
    PodcastSubscriptionPatchIn,
)
from app.models.art import ENTITY_PODCAST, ROLE_COVER
from app.models.media_file import MediaFile, ScanState
from app.models.podcast import (
    Podcast, PodcastEpisode, PodcastEpisodeProgress, PodcastSubscription,
)
from app.models.user import User
from app.services import longform, net_guard
from app.services.art import resolve_art_batch
from app.services.podcasts import media_types, opml
from app.services.podcasts import refresh as refresh_service
from app.services.podcasts import search as podcast_search

log = logging.getLogger("f7five0.api.podcasts")

router = APIRouter()

PAGE_DEFAULT = 200
PAGE_MAX = 500
IN_PROGRESS_LIMIT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Presenters
# ---------------------------------------------------------------------------
def _art_map(db: Session, pod_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    return resolve_art_batch(db, entity_kind=ENTITY_PODCAST, entity_ids=set(pod_ids), role=ROLE_COVER)


def _podcast_out(db: Session, user: User, pods: list[Podcast]) -> list[PodcastOut]:
    """Shows as the caller sees them: whether they follow it, and counts."""
    if not pods:
        return []
    ids = [p.id for p in pods]
    subs = {
        s.podcast_id: s for s in db.scalars(select(PodcastSubscription).where(
            PodcastSubscription.user_id == user.id, PodcastSubscription.podcast_id.in_(ids),
        ))
    }
    counts = dict(db.execute(
        select(PodcastEpisode.podcast_id, func.count()).where(PodcastEpisode.podcast_id.in_(ids))
        .group_by(PodcastEpisode.podcast_id)
    ).all())
    files = dict(db.execute(
        select(PodcastEpisode.podcast_id, func.count())
        .join(MediaFile, MediaFile.id == PodcastEpisode.media_file_id)
        .where(PodcastEpisode.podcast_id.in_(ids), MediaFile.scan_state == ScanState.ready)
        .group_by(PodcastEpisode.podcast_id)
    ).all())
    art = _art_map(db, ids)
    return [
        PodcastOut(
            id=p.id, title=p.title, author=p.author, description=p.description,
            feed_url=p.feed_url, source=p.source, art_url=art.get(p.id),
            subscribed=p.id in subs,
            auto_download=bool(subs[p.id].auto_download) if p.id in subs else False,
            episode_count=int(counts.get(p.id, 0)), files_on_server=int(files.get(p.id, 0)),
            last_checked_at=p.last_checked_at, last_error=p.last_error,
        )
        for p in pods
    ]


def _episode_state(row: Optional[PodcastEpisodeProgress]) -> dict:
    if row is None:
        return longform.state_for(position_sec=None, played=False)
    return longform.state_for(position_sec=row.position_sec, played=row.played_at is not None)


def _episodes_out(db: Session, user: User, episodes: list[PodcastEpisode]) -> list[PodcastEpisodeOut]:
    """Episodes with the caller's own state."""
    if not episodes:
        return []
    ids = [e.id for e in episodes]
    pods = {
        p.id: p for p in db.scalars(select(Podcast).where(Podcast.id.in_({e.podcast_id for e in episodes})))
    }
    progress = {
        r.episode_id: r for r in db.scalars(select(PodcastEpisodeProgress).where(
            PodcastEpisodeProgress.user_id == user.id, PodcastEpisodeProgress.episode_id.in_(ids),
        ))
    }
    file_ids = [e.media_file_id for e in episodes if e.media_file_id]
    files = {
        mf.id: mf for mf in db.scalars(select(MediaFile).where(MediaFile.id.in_(file_ids)))
    } if file_ids else {}
    art = _art_map(db, pods.keys())
    out = []
    for e in episodes:
        mf = files.get(e.media_file_id) if e.media_file_id else None
        has_file = mf is not None and mf.scan_state == ScanState.ready
        container = mf.container if has_file and mf.container else media_types.ext_for(e.enclosure_type, e.enclosure_url)
        out.append(PodcastEpisodeOut(
            id=e.id, podcast_id=e.podcast_id, podcast_title=pods[e.podcast_id].title,
            art_url=art.get(e.podcast_id), title=e.title, description=e.description,
            published_at=e.published_at, duration_sec=e.duration_sec, season=e.season,
            episode=e.episode, is_video=media_types.is_video_type(e.enclosure_type),
            has_file=has_file, downloaded_by_f7five0=bool(e.downloaded_by_f7five0),
            container=container, has_chapters=bool(e.chapters_url or e.chapters_json),
            state=_episode_state(progress.get(e.id)),
        ))
    return out


def _get_show(db: Session, show_id: uuid.UUID) -> Podcast:
    pod = db.get(Podcast, show_id)
    if pod is None:
        raise HTTPException(status_code=404, detail="podcast_not_found")
    return pod


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@router.get("/search", response_model=PodcastSearchOut)
def search_podcasts(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    _user: Annotated[User, Depends(current_user)],
) -> PodcastSearchOut:
    """Search the podcast directory: Podcast Index when the server has a key,
    Apple's iTunes Search API when it does not. Each result is a title, author,
    art URL, feed URL and the provider; subscribing is `POST /subscribe`."""
    try:
        found = podcast_search.search(q)
    except podcast_search.SearchError as exc:
        log.warning("podcast search failed (%s)", exc.kind)
        raise HTTPException(status_code=502, detail="search_failed") from None
    return PodcastSearchOut(
        provider=found.provider,
        results=[PodcastSearchResultOut(**r) for r in found.results],
    )


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------
@router.get("", response_model=PodcastHomeOut)
def podcasts_home(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PodcastHomeOut:
    """The Podcasts page: what the caller is partway through, the shows they
    follow, and the shows with files in a podcasts folder on this server."""
    latest = (
        select(PodcastEpisode.podcast_id, func.max(PodcastEpisode.published_at).label("latest"))
        .group_by(PodcastEpisode.podcast_id).subquery()
    )
    mine = db.scalars(
        select(Podcast)
        .join(PodcastSubscription, PodcastSubscription.podcast_id == Podcast.id)
        .outerjoin(latest, latest.c.podcast_id == Podcast.id)
        .where(PodcastSubscription.user_id == user.id)
        .order_by(latest.c.latest.desc().nulls_last(), Podcast.title)
    ).all()
    on_server = db.scalars(
        select(Podcast).where(Podcast.id.in_(
            select(PodcastEpisode.podcast_id)
            .join(MediaFile, MediaFile.id == PodcastEpisode.media_file_id)
            .where(MediaFile.scan_state == ScanState.ready)
        )).order_by(Podcast.title)
    ).all()
    partway = db.scalars(
        select(PodcastEpisode)
        .join(PodcastEpisodeProgress, PodcastEpisodeProgress.episode_id == PodcastEpisode.id)
        .where(
            PodcastEpisodeProgress.user_id == user.id,
            PodcastEpisodeProgress.position_sec > 0,
            PodcastEpisodeProgress.played_at.is_(None),
        )
        .order_by(PodcastEpisodeProgress.updated_at.desc())
        .limit(IN_PROGRESS_LIMIT)
    ).all()
    return PodcastHomeOut(
        in_progress=_episodes_out(db, user, list(partway)),
        mine=_podcast_out(db, user, list(mine)),
        on_server=_podcast_out(db, user, list(on_server)),
    )


# ---------------------------------------------------------------------------
# Subscribe, unsubscribe, auto-download
# ---------------------------------------------------------------------------
def _ensure_subscription(db: Session, user: User, pod: Podcast) -> bool:
    """Subscribe the caller. Returns True when this made a new subscription."""
    if db.get(PodcastSubscription, (user.id, pod.id)) is not None:
        return False
    db.add(PodcastSubscription(user_id=user.id, podcast_id=pod.id, auto_download=False, created_at=_now()))
    db.flush()
    return True


@router.post("/subscribe", response_model=PodcastOut)
def subscribe(
    body: PodcastSubscribeIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PodcastOut:
    """Follow a show by its feed URL (from search, or pasted) or, for a show
    found in a podcasts folder, by its id. A new feed is fetched now, so a feed
    that cannot be read answers an error and leaves nothing behind."""
    if body.podcast_id is not None:
        pod = _get_show(db, body.podcast_id)
    else:
        try:
            pod, _created = refresh_service.get_or_create_show(db, body.feed_url or "")
        except refresh_service.SubscribeError as exc:
            db.rollback()
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from None
        except IntegrityError:
            # Somebody added the same feed a moment ago.
            db.rollback()
            pod = db.scalar(select(Podcast).where(Podcast.feed_url == body.feed_url))
            if pod is None:
                raise HTTPException(status_code=409, detail="try_again") from None
    _ensure_subscription(db, user, pod)
    db.commit()
    return _podcast_out(db, user, [pod])[0]


@router.delete("/{id}/subscription", status_code=204)
def unsubscribe(
    id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    sub = db.get(PodcastSubscription, (user.id, id))
    if sub is None:
        raise HTTPException(status_code=404, detail="not_subscribed")
    db.delete(sub)
    db.commit()
    return Response(status_code=204)


@router.patch("/{id}/subscription", response_model=PodcastSubscriptionOut)
def patch_subscription(
    id: uuid.UUID,
    body: PodcastSubscriptionPatchIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PodcastSubscriptionOut:
    """Turn auto-download on or off for the caller's own subscription."""
    sub = db.get(PodcastSubscription, (user.id, id))
    if sub is None:
        raise HTTPException(status_code=404, detail="not_subscribed")
    sub.auto_download = body.auto_download
    db.commit()
    return PodcastSubscriptionOut(
        podcast_id=sub.podcast_id, auto_download=sub.auto_download, created_at=sub.created_at,
    )


# ---------------------------------------------------------------------------
# OPML
# ---------------------------------------------------------------------------
@router.get("/opml")
def export_opml(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """The caller's subscriptions as an OPML 2.0 file (shows with a feed)."""
    rows = db.execute(
        select(Podcast.title, Podcast.feed_url)
        .join(PodcastSubscription, PodcastSubscription.podcast_id == Podcast.id)
        .where(PodcastSubscription.user_id == user.id, Podcast.feed_url.is_not(None))
        .order_by(Podcast.title)
    ).all()
    data = opml.export_opml((title, None, url) for title, url in rows)
    return Response(
        content=data, media_type="text/x-opml+xml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="f7five0-podcasts.opml"'},
    )


@router.post("/opml", response_model=PodcastOpmlResultOut)
def import_opml(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PodcastOpmlResultOut:
    """Follow every feed in an OPML file (up to 1 MB). Answers how many were
    added, were already followed, or could not be used. New shows are fetched in
    the background, not in this request."""
    data = file.file.read(net_guard.OPML_MAX_BYTES + 1)
    if len(data) > net_guard.OPML_MAX_BYTES:
        raise HTTPException(status_code=413, detail="opml_too_large")
    try:
        urls = opml.parse_opml(data)
    except opml.OpmlError:
        raise HTTPException(status_code=400, detail="invalid_opml") from None

    added = already = failed = 0
    new_ids: list[uuid.UUID] = []
    for i, raw in enumerate(urls):
        if i >= opml.MAX_FEEDS_PER_IMPORT:
            failed += len(urls) - i
            break
        try:
            url = refresh_service.normalize_feed_url(raw)
        except refresh_service.SubscribeError:
            failed += 1
            continue
        pod, created = refresh_service.add_placeholder_show(db, url)
        if created:
            new_ids.append(pod.id)
        if _ensure_subscription(db, user, pod):
            added += 1
        else:
            already += 1
    db.commit()
    if new_ids:
        scheduler.trigger_podcast_refresh_now(new_ids)
    return PodcastOpmlResultOut(added=added, already=already, failed=failed)


# ---------------------------------------------------------------------------
# One show
# ---------------------------------------------------------------------------
@router.get("/{id}", response_model=PodcastDetailOut)
def get_podcast(
    id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PodcastDetailOut:
    """A show and its episodes, newest first, each with the caller's own state."""
    pod = _get_show(db, id)
    total = db.scalar(select(func.count()).select_from(PodcastEpisode).where(PodcastEpisode.podcast_id == id)) or 0
    episodes = db.scalars(
        select(PodcastEpisode).where(PodcastEpisode.podcast_id == id)
        .order_by(PodcastEpisode.published_at.desc().nulls_last(), PodcastEpisode.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return PodcastDetailOut(
        podcast=_podcast_out(db, user, [pod])[0],
        episodes=_episodes_out(db, user, list(episodes)),
        total=int(total),
    )
