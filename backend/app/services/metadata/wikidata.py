"""Wikidata: find an artist's English Wikipedia article.

MusicBrainz links most artists to Wikidata (a `wikidata` url-rel such as
`https://www.wikidata.org/wiki/Q44190`) and only a few straight to Wikipedia,
so the artist bio has to go Wikidata -> English Wikipedia title -> summary.
`enwiki_title(qid_or_url)` returns the title from the item's `enwiki`
sitelink, or None when the item has no English article.

    GET https://www.wikidata.org/w/api.php?action=wbgetentities&ids=<Q>
        &props=sitelinks&sitefilter=enwiki&format=json

No API key. Paced at 5 req/s and cached on disk like the other providers.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from app.services.metadata._base import (
    ProviderError,
    cache_read,
    cache_write,
    http_client,
    is_negative,
)


log = logging.getLogger("f7five0.metadata.wikidata")

_QID_RE = re.compile(r"\b(Q[1-9][0-9]*)\b")
_MIN_INTERVAL_SEC = 0.2
_pace_lock = threading.Lock()
_last_request_at = 0.0


def _pace() -> None:
    global _last_request_at
    with _pace_lock:
        now = time.monotonic()
        wait = (_last_request_at + _MIN_INTERVAL_SEC) - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _last_request_at = now


def qid_from(value: Optional[str]) -> Optional[str]:
    """`Q44190` from a bare id or any Wikidata URL; None otherwise."""
    if not value:
        return None
    m = _QID_RE.search(value)
    return m.group(1) if m else None


class WikidataClient:
    BASE_URL = "https://www.wikidata.org/w/api.php"
    PROVIDER = "wikidata"

    def __init__(self) -> None:
        self._client = http_client()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WikidataClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def enwiki_title(self, qid_or_url: str) -> Optional[str]:
        """English Wikipedia title for a Wikidata item, or None."""
        qid = qid_from(qid_or_url)
        if not qid:
            return None
        cached = cache_read(self.PROVIDER, qid)
        if cached is not None:
            return None if is_negative(cached) else cached.get("title")
        _pace()
        try:
            resp = self._client.get(self.BASE_URL, params={
                "action": "wbgetentities", "ids": qid, "props": "sitelinks",
                "sitefilter": "enwiki", "format": "json",
            })
        except Exception as exc:
            raise ProviderError(f"wikidata GET {qid} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"wikidata returned {resp.status_code} for {qid}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderError(f"wikidata answer for {qid} was not JSON") from exc
        entity = ((body or {}).get("entities") or {}).get(qid) or {}
        title = ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title")
        if not title:
            cache_write(self.PROVIDER, qid, {"status": "not_found"})
            return None
        cache_write(self.PROVIDER, qid, {"title": title})
        return title
