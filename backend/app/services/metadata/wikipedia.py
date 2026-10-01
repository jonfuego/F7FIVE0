"""Wikipedia REST API summary fetcher.

`get_extract(url_or_title)` returns the summary payload Wikipedia
publishes at `/api/rest_v1/page/summary/<title>`. The caller may pass
either the bare title or a full Wikipedia URL (the way MusicBrainz
returns it on `url-rels`); the URL is parsed down to the title.

No API key. Polite throttle at 5 req/s.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional
from urllib.parse import quote, unquote, urlparse

from app.services.metadata._base import (
    ProviderError,
    cache_read,
    cache_write,
    http_client,
    is_negative,
)


log = logging.getLogger("f7five0.metadata.wikipedia")

_MIN_INTERVAL_SEC = 0.2  # 5 req/s
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


class WikipediaClient:
    BASE_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
    PROVIDER = "wikipedia"

    def __init__(self) -> None:
        self._client = http_client()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WikipediaClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @staticmethod
    def _title_from_url(value: str) -> str:
        if "://" not in value:
            return value
        parsed = urlparse(value)
        path = parsed.path or ""
        marker = "/wiki/"
        if path.startswith(marker):
            return unquote(path[len(marker):])
        return value

    def get_extract(self, url_or_title: str) -> Optional[dict]:
        """Return the summary payload for a Wikipedia article (`extract`,
        `description`, etc.). None on 404 or empty input."""
        title = self._title_from_url(url_or_title)
        if not title:
            return None
        cache_key = title.replace("/", "_")
        cached = cache_read(self.PROVIDER, cache_key)
        if cached is not None:
            return None if is_negative(cached) else cached
        _pace()
        try:
            resp = self._client.get(
                f"{self.BASE_URL}/{quote(title, safe='')}",
            )
        except Exception as exc:
            raise ProviderError(
                f"wikipedia GET {title!r} failed: {exc}",
            ) from exc
        if resp.status_code == 404:
            cache_write(self.PROVIDER, cache_key, {"status": "not_found"})
            return None
        if resp.status_code >= 400:
            raise ProviderError(
                f"wikipedia returned {resp.status_code} for {title!r}",
            )
        payload = resp.json()
        cache_write(self.PROVIDER, cache_key, payload)
        return payload


def _smoke(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: python -m app.services.metadata.wikipedia <title|url>",
            file=sys.stderr,
        )
        return 2
    with WikipediaClient() as cli:
        result = cli.get_extract(argv[1])
    if result is None:
        print("no result")
        return 1
    print({"title": result.get("title"), "description": result.get("description")})
    print()
    print(result.get("extract"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke(sys.argv))
