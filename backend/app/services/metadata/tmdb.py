"""TMDB v3 movie + credits client.

Fetches movie records with cast and crew embedded via
`append_to_response=credits`. Disk-cached per movie id. Token-bucket
rate limit at 40 requests per 10-second window enforced at module
scope so multiple threads can't outrun the upstream cap.

When no key is set (Admin > Metadata or TMDB_API_KEY) the client returns None immediately. The
runner treats that as `metadata_status = no_external_id` for the row.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from typing import Optional

from app.services import tmdb_key
from app.services.metadata._base import (
    ProviderError,
    cache_read,
    cache_write,
    http_client,
    is_negative,
)


log = logging.getLogger("f7five0.metadata.tmdb")

# Token-bucket rate limit: 40 requests per 10-second window.
_RATE_LIMIT_REQUESTS = 40
_RATE_LIMIT_WINDOW_SEC = 10.0
_rate_lock = threading.Lock()
_rate_window: deque[float] = deque()


def _rate_wait() -> None:
    """Block until a request slot is available. Called once per HTTP fire."""
    while True:
        with _rate_lock:
            now = time.monotonic()
            cutoff = now - _RATE_LIMIT_WINDOW_SEC
            while _rate_window and _rate_window[0] < cutoff:
                _rate_window.popleft()
            if len(_rate_window) < _RATE_LIMIT_REQUESTS:
                _rate_window.append(now)
                return
            sleep_for = _rate_window[0] - cutoff
        time.sleep(max(sleep_for, 0.05))


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"
    PROVIDER = "tmdb"

    def __init__(self) -> None:
        self._client = http_client()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TMDBClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def get_movie(self, tmdb_id: int) -> Optional[dict]:
        """Return the parsed TMDB record for `tmdb_id`. None when no key
        is configured or the upstream returns 404. Raises ProviderError
        on other HTTP failures."""
        api_key = tmdb_key.get()
        if not api_key:
            return None
        key = f"movie_{int(tmdb_id)}"
        cached = cache_read(self.PROVIDER, key)
        if cached is not None:
            return None if is_negative(cached) else cached

        _rate_wait()
        try:
            resp = self._client.get(
                f"{self.BASE_URL}/movie/{int(tmdb_id)}",
                params={
                    "api_key": api_key,
                    "append_to_response": "credits",
                },
            )
        except Exception as exc:
            raise ProviderError(
                f"tmdb GET movie/{tmdb_id} failed: {exc}",
            ) from exc

        if resp.status_code == 404:
            cache_write(self.PROVIDER, key, {"status": "not_found"})
            return None
        if resp.status_code >= 400:
            raise ProviderError(
                f"tmdb returned {resp.status_code} for movie/{tmdb_id}",
            )
        payload = resp.json()
        cache_write(self.PROVIDER, key, payload)
        return payload

    def search(self, kind: str, title: str, year: Optional[int] = None) -> Optional[dict]:
        """Best title/year match for `kind` ("movie" or "tv"), or None.

        Used by the folder scanner to match libraries that have no *arr ids.
        Returns the first TMDB search hit (id, overview, poster_path,
        backdrop_path, release_date / first_air_date). Cached on disk like
        every other TMDB call, including misses."""
        api_key = tmdb_key.get()
        if not api_key or kind not in ("movie", "tv") or not title:
            return None
        key = f"search_{kind}_{title.lower()}_{year or ''}"
        cached = cache_read(self.PROVIDER, key)
        if cached is not None:
            return None if is_negative(cached) else cached

        params = {"api_key": api_key, "query": title, "include_adult": "false"}
        if year:
            params["year" if kind == "movie" else "first_air_date_year"] = str(year)
        _rate_wait()
        try:
            resp = self._client.get(f"{self.BASE_URL}/search/{kind}", params=params)
        except Exception as exc:
            raise ProviderError(f"tmdb search/{kind} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"tmdb returned {resp.status_code} for search/{kind}")
        results = (resp.json() or {}).get("results") or []
        if not results and year:
            # Folder years are often off by one; retry without the year.
            return self.search(kind, title, None)
        if not results:
            cache_write(self.PROVIDER, key, {"status": "not_found"})
            return None
        hit = results[0]
        cache_write(self.PROVIDER, key, hit)
        return hit


def _smoke(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m app.services.metadata.tmdb <tmdb_id>", file=sys.stderr)
        return 2
    tid = int(argv[1])
    with TMDBClient() as cli:
        result = cli.get_movie(tid)
    if result is None:
        print("no result (key missing or 404)")
        return 1
    title = result.get("title")
    cast = (result.get("credits") or {}).get("cast") or []
    crew = (result.get("credits") or {}).get("crew") or []
    directors = [c.get("name") for c in crew if c.get("job") == "Director"]
    print(f"title: {title}")
    print(f"tagline: {result.get('tagline')}")
    print(
        f"vote_average: {result.get('vote_average')} "
        f"vote_count: {result.get('vote_count')}",
    )
    print(f"directors: {directors}")
    print(f"cast (top 5): {[c.get('name') for c in cast[:5]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke(sys.argv))
