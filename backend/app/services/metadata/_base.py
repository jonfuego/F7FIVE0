"""Shared plumbing for the metadata providers.

Three things live here:
- An httpx.Client factory with the project User-Agent and a 10s timeout.
- Disk-cache helpers `cache_read` / `cache_write` rooted at
  `<METADATA_CACHE_ROOT>/<provider>/<key>.json`. TTL is checked via the
  file's mtime against `METADATA_TTL_DAYS`.
- A `ProviderError` raised on non-cacheable HTTP failures (5xx, network
  errors). 404s get a sentinel write `{"status": "not_found"}` so we
  don't hammer the upstream on rows the caller will keep retrying.

Cache root is created on first write so a runner does not crash on a
fresh box that has no metadata cache folder yet.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from app.config import PROJECT_URL, settings


log = logging.getLogger("f7five0.metadata")

USER_AGENT = f"F7FIVE0/1.0 (+{PROJECT_URL})"


class ProviderError(RuntimeError):
    """Non-cacheable upstream HTTP failure. The caller logs and tags the
    row's metadata_status as failed but does not write a sentinel."""


def _safe_key(value: str) -> str:
    """Make `value` safe to use as a flat NTFS filename. Anything outside
    [A-Za-z0-9._-] collapses to underscore. The provider key namespace is
    short and well-formed (uuid / int) so collisions aren't a practical
    concern."""
    out = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "_"


def _cache_path(provider: str, key: str) -> Path:
    root = Path(settings.metadata_cache_root)
    return root / provider / f"{_safe_key(key)}.json"


def cache_read(provider: str, key: str) -> Optional[dict]:
    """Return the cached JSON for (provider, key) when present and fresh.
    None when missing, expired, or unreadable."""
    path = _cache_path(provider, key)
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    age_sec = time.time() - st.st_mtime
    ttl_sec = settings.metadata_ttl_days * 86400
    if age_sec > ttl_sec:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def cache_write(provider: str, key: str, payload: dict) -> None:
    """Atomic disk-cache write via tmp + os.replace. Best-effort: a
    failed cache write logs and swallows so the runner still gets the
    parsed payload."""
    path = _cache_path(provider, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        log.exception("metadata cache write failed for %s/%s", provider, key)


def is_negative(payload: Optional[dict]) -> bool:
    """True when a cached payload is the 404 sentinel."""
    return isinstance(payload, dict) and payload.get("status") == "not_found"


def http_client(
    timeout: float = 10.0,
    headers: Optional[dict[str, str]] = None,
) -> httpx.Client:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    return httpx.Client(timeout=timeout, headers=h)
