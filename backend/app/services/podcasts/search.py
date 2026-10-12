"""Find podcasts in a directory.

With a Podcast Index key and secret (Admin > Metadata, or `.env`) search uses
Podcast Index `search/byterm`, signed per its docs: `X-Auth-Key`, `X-Auth-Date`
(unix time) and `Authorization` = SHA-1 of key + secret + date, plus a
User-Agent. With no key it uses Apple's iTunes Search API (`media=podcast`),
which needs none. Either way the answer is the same small shape: title, author,
art URL, feed URL and which provider it came from.

Every request goes through `net_guard`. Nothing here logs the key, the secret
or the signed headers; a failure is reported by class and status only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from app.services import net_guard, podcastindex_key

log = logging.getLogger("f7five0.podcasts.search")

PODCASTINDEX_URL = "https://api.podcastindex.org/api/1.0/search/byterm"
ITUNES_URL = "https://itunes.apple.com/search"
MAX_SEARCH_BYTES = 2 * 1024 * 1024
DEFAULT_LIMIT = 25

PROVIDER_PODCASTINDEX = "podcastindex"
PROVIDER_ITUNES = "itunes"


class SearchError(Exception):
    """The directory could not be searched. `kind` is "auth" when Podcast Index
    rejected the key, else "unavailable". The message is safe to show."""

    def __init__(self, message: str, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class SearchResponse:
    provider: str
    results: list[dict]


def provider_name() -> str:
    return PROVIDER_PODCASTINDEX if podcastindex_key.configured() else PROVIDER_ITUNES


def signed_headers(key: str, secret: str, now: Optional[int] = None) -> dict:
    """The headers Podcast Index wants on every request."""
    stamp = str(int(now if now is not None else time.time()))
    return {
        "X-Auth-Date": stamp,
        "X-Auth-Key": key,
        "Authorization": hashlib.sha1((key + secret + stamp).encode("utf-8")).hexdigest(),
        "Accept": "application/json",
    }


def _get_json(url: str, headers: Optional[dict] = None) -> dict:
    try:
        fetched = net_guard.fetch_bytes(url, max_bytes=MAX_SEARCH_BYTES, headers=headers)
    except net_guard.NetGuardError as exc:
        status = exc.upstream_status
        log.warning("podcast directory search failed: %s%s", type(exc).__name__,
                    f" (HTTP {status})" if status else "")
        if status in (401, 403):
            raise SearchError("The directory rejected the request.", "auth") from None
        raise SearchError("The podcast directory could not be reached.") from None
    try:
        data = json.loads(fetched.body.decode("utf-8", errors="replace"))
    except ValueError:
        raise SearchError("The podcast directory answered something unexpected.") from None
    if not isinstance(data, dict):
        raise SearchError("The podcast directory answered something unexpected.")
    return data


def _text(value: object) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) and str(value).strip() else ""


def _http(value: object) -> Optional[str]:
    text = _text(value)
    return text if text.lower().startswith(("http://", "https://")) else None


def _podcastindex(q: str, key: str, secret: str, limit: int) -> list[dict]:
    url = f"{PODCASTINDEX_URL}?{urlencode({'q': q, 'max': limit})}"
    data = _get_json(url, signed_headers(key, secret))
    out = []
    for feed in data.get("feeds") or []:
        feed_url = _http(feed.get("url"))
        title = _text(feed.get("title"))
        if not feed_url or not title:
            continue
        out.append({
            "title": title,
            "author": _text(feed.get("author")) or _text(feed.get("ownerName")),
            "art_url": _http(feed.get("image")) or _http(feed.get("artwork")),
            "feed_url": feed_url,
            "provider": PROVIDER_PODCASTINDEX,
        })
    return out


def _itunes(q: str, limit: int) -> list[dict]:
    url = f"{ITUNES_URL}?{urlencode({'media': 'podcast', 'entity': 'podcast', 'term': q, 'limit': limit})}"
    data = _get_json(url)
    out = []
    for item in data.get("results") or []:
        feed_url = _http(item.get("feedUrl"))
        title = _text(item.get("collectionName") or item.get("trackName"))
        if not feed_url or not title:
            continue
        out.append({
            "title": title,
            "author": _text(item.get("artistName")),
            "art_url": _http(item.get("artworkUrl600")) or _http(item.get("artworkUrl100")),
            "feed_url": feed_url,
            "provider": PROVIDER_ITUNES,
        })
    return out


def search(q: str, *, limit: int = DEFAULT_LIMIT) -> SearchResponse:
    """Search the directory for `q`. Raises SearchError."""
    q = (q or "").strip()
    key, secret = podcastindex_key.get()
    if key and secret:
        return SearchResponse(PROVIDER_PODCASTINDEX, _podcastindex(q, key, secret, limit))
    return SearchResponse(PROVIDER_ITUNES, _itunes(q, limit))


def check_credentials(key: str, secret: str) -> tuple[bool, str]:
    """Ask Podcast Index whether a key and secret work, by running one search.
    Returns (ok, message); the message never contains the key or secret."""
    key, secret = (key or "").strip(), (secret or "").strip()
    if not key or not secret:
        return False, "Enter both the key and the secret first."
    try:
        _podcastindex("podcast", key, secret, 1)
    except SearchError as exc:
        if exc.kind == "auth":
            return False, "Podcast Index rejected that key and secret. Copy both from your api.podcastindex.org account."
        return False, "Could not reach Podcast Index from the server. Check its internet connection."
    return True, "Podcast Index accepted the key and secret."
