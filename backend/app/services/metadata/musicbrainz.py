"""MusicBrainz v2 client.

`get_artist(mbid)` fetches an artist record with tags, URL relations,
and annotations. `get_release_group(mbid)` fetches an album / release-
group record with tags, ratings, and the release list.

MusicBrainz requires a real contact email in the User-Agent per their
ToS. The string is built from `MUSICBRAINZ_USER_AGENT_EMAIL`. Hard rate
limit is 1 request per second across the whole process; a module-level
threading.Lock plus monotonic-clock pacing enforces it.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional

from app.config import PROJECT_URL, settings
from app.services.metadata._base import (
    ProviderError,
    cache_read,
    cache_write,
    http_client,
    is_negative,
)


log = logging.getLogger("f7five0.metadata.musicbrainz")

_MIN_INTERVAL_SEC = 1.0
_pace_lock = threading.Lock()
_last_request_at = 0.0


def _pace() -> None:
    """Block until 1 second has passed since the last MB request. Holds
    the lock while sleeping so concurrent callers serialize cleanly."""
    global _last_request_at
    with _pace_lock:
        now = time.monotonic()
        wait = (_last_request_at + _MIN_INTERVAL_SEC) - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _last_request_at = now


class MusicBrainzClient:
    BASE_URL = "https://musicbrainz.org/ws/2"
    PROVIDER = "musicbrainz"

    def __init__(self) -> None:
        contact = settings.musicbrainz_user_agent_email or PROJECT_URL
        ua = f"F7FIVE0/1.0 ( {contact} )"
        self._client = http_client(headers={"User-Agent": ua})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MusicBrainzClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _fetch(
        self, path: str, params: dict[str, str], cache_key: str,
    ) -> Optional[dict]:
        cached = cache_read(self.PROVIDER, cache_key)
        if cached is not None:
            return None if is_negative(cached) else cached
        _pace()
        try:
            resp = self._client.get(f"{self.BASE_URL}/{path}", params=params)
        except Exception as exc:
            raise ProviderError(
                f"musicbrainz GET {path} failed: {exc}",
            ) from exc
        if resp.status_code == 404:
            cache_write(self.PROVIDER, cache_key, {"status": "not_found"})
            return None
        if resp.status_code >= 400:
            raise ProviderError(
                f"musicbrainz returned {resp.status_code} for {path}",
            )
        payload = resp.json()
        cache_write(self.PROVIDER, cache_key, payload)
        return payload

    def get_artist(self, mbid: str) -> Optional[dict]:
        return self._fetch(
            f"artist/{mbid}",
            {"inc": "tags+url-rels+annotation", "fmt": "json"},
            f"artist_{mbid}",
        )

    def get_release_group(self, mbid: str) -> Optional[dict]:
        return self._fetch(
            f"release-group/{mbid}",
            {"inc": "tags+annotation+ratings+releases", "fmt": "json"},
            f"release_group_{mbid}",
        )


def _smoke(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: python -m app.services.metadata.musicbrainz "
            "<artist|rg> <mbid>",
            file=sys.stderr,
        )
        return 2
    kind, mbid = argv[1], argv[2]
    with MusicBrainzClient() as cli:
        if kind == "artist":
            result = cli.get_artist(mbid)
        elif kind == "rg":
            result = cli.get_release_group(mbid)
        else:
            print("kind must be 'artist' or 'rg'", file=sys.stderr)
            return 2
    if result is None:
        print("no result")
        return 1
    interesting = ("name", "type", "country", "life-span", "title", "primary-type")
    print({k: result.get(k) for k in interesting if k in result})
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke(sys.argv))
