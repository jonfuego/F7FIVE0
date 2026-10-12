"""Podcasts for signed-in users: search, subscribe, progress, chapters, downloads.

Every route needs a signed-in user (`current_user`); the Admin routes (storage,
refresh, removing a server download, the Podcast Index key) live in
`api/admin.py` behind `require_admin`. The web reaches these through the library
BFF (`/api/library/podcasts/...` -> `/api/podcasts/...`); the app calls them
directly with its Bearer token.

Static paths (`/search`, `/opml`, `/subscribe`, `/episodes/...`) are declared
before `/{id}` routes so they are never read as a show id.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import current_user
from app.api.schemas import PodcastSearchOut, PodcastSearchResultOut
from app.models.user import User
from app.services.podcasts import search as podcast_search

log = logging.getLogger("f7five0.api.podcasts")

router = APIRouter()


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
