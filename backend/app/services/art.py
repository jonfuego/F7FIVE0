"""Admin art overrides: read-through lookup + write helpers.

resolve_art() is the read path used by library schemas. Upload / URL
writers decode every byte stream with Pillow before trusting the format
so content-type sniffing and filename extensions are not in the trust
boundary.

Files land under settings.art_root at <kind>/<uuid>/<role>.<ext>. Atomic
writes use the tempfile + os.replace pattern so a partial download can
never replace a live asset.
"""
from __future__ import annotations

import io
import ipaddress
import logging
import os
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PROJECT_URL, settings
from app.models.art import (
    ArtOverride, ENTITY_ALBUM, ENTITY_ARTIST, ENTITY_MOVIE, ENTITY_MUSIC_VIDEO,
    ENTITY_SERIES, ROLE_BACKDROP, ROLE_COVER, ROLE_POSTER, ROLE_THUMB,
)


log = logging.getLogger("f7five0.art")


# Fixed UUID for the synthetic system user that owns sync-originated
# override rows. Seeded by the 0017_local_first_art migration; row is
# is_active=False so it can never authenticate. Used as set_by when
# download_art_on_sync writes an art_overrides row.
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# source_kind values that originate from an *arr sync. Used by
# download_art_on_sync to detect whether an existing override came from
# an admin (which we never clobber) or from a prior sync (which we may
# refresh when the URL changes).
_ARR_SOURCE_KINDS: frozenset[str] = frozenset({"lidarr", "radarr", "sonarr"})


# Accepted image formats after Pillow decode. Keys are Pillow's format
# name; values are the canonical extension we store on disk.
_ALLOWED_FORMATS: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}

# 10 MB cap on any uploaded or fetched image. Larger than any sane
# poster but small enough that a runaway download gets stopped.
_MAX_BYTES = 10 * 1024 * 1024

# Hard timeout for URL fetches.
_URL_TIMEOUT = 10.0

# Max redirect hops on an admin art URL fetch. Generous enough for normal
# CDN chains, bounded so a redirect loop can't spin forever and so each hop
# stays inside the SSRF check below.
_MAX_REDIRECTS = 5


def _assert_public_host(url: str) -> None:
    """Reject a URL whose host resolves to a non-public address.

    SSRF guard for the admin URL-paste path: a pasted URL must not be usable
    to probe LAN or localhost services. Resolves every address the host maps
    to and rejects loopback, private, link-local, reserved, unspecified, and
    multicast ranges. Called on the original URL and again on every redirect
    target so a public URL can't bounce the fetch onto an internal one.
    """
    host = (urlsplit(url).hostname or "").strip()
    if not host:
        raise ArtValidationError("url has no host", status_code=400)
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ArtValidationError(
            f"cannot resolve host {host}: {exc}", status_code=502,
        )
    for info in infos:
        raw = info[4][0].split("%")[0]  # strip any IPv6 scope id
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            raise ArtValidationError(
                f"unresolvable address for {host}", status_code=502,
            )
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_unspecified or ip.is_multicast
        ):
            raise ArtValidationError(
                f"refusing to fetch from non-public address ({ip})",
                status_code=400,
            )

# Valid (entity_kind, role) combinations. Reject anything else at the
# service layer so garbage can never land in the table.
_VALID_ROLES: dict[str, set[str]] = {
    ENTITY_ARTIST: {ROLE_THUMB},
    ENTITY_ALBUM: {ROLE_COVER},
    ENTITY_MUSIC_VIDEO: {ROLE_THUMB},
    ENTITY_MOVIE: {ROLE_POSTER, ROLE_BACKDROP},
    ENTITY_SERIES: {ROLE_POSTER, ROLE_BACKDROP},
}


class ArtValidationError(ValueError):
    """Raised when an upload or URL fetch fails validation.

    The HTTP layer turns this into a 4xx. Message is safe to surface to
    the admin — the error path is a deliberate user-facing check, not an
    internal invariant failure.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_kind_role(entity_kind: str, role: str) -> None:
    roles = _VALID_ROLES.get(entity_kind)
    if roles is None:
        raise ArtValidationError(
            f"unsupported entity kind: {entity_kind}", status_code=404,
        )
    if role not in roles:
        raise ArtValidationError(
            f"role '{role}' not valid for {entity_kind}", status_code=400,
        )


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------
def resolve_art(
    db: Session,
    *,
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
) -> Optional[str]:
    """Return a client-ready path for the requested art, or None.

    Since the local-first-art-on-sync change, art_overrides is the single
    source of truth. Sync downloads every image and writes an override
    row, so any entity without a row genuinely has no art (frontend
    renders the placeholder tile).
    """
    row = db.get(ArtOverride, (entity_kind, entity_id, role))
    if row is None:
        return None
    # Same-origin URL the browser can hit directly. Cache-bust via
    # ?v=<set_at_unix> so a re-pick invalidates the browser cache without
    # touching Cache-Control headers. Integer seconds is enough — admins
    # don't flip the same entity twice in the same second.
    cache_key = int(row.set_at.timestamp())
    return f"/api/art/{entity_kind}/{entity_id}/{role}?v={cache_key}"


def resolve_art_batch(
    db: Session,
    *,
    entity_kind: str,
    entity_ids: Iterable[uuid.UUID],
    role: str,
) -> dict[uuid.UUID, str]:
    """Batch counterpart to resolve_art for list endpoints.

    Issues exactly one SELECT against `art_overrides` for the provided
    ids and returns a `{entity_id: art-url}` mapping. Ids without an
    override row are absent from the dict; callers project `None` for
    those rows. The url shape matches resolve_art so the frontend
    doesn't see a difference.

    Empty input returns an empty dict and skips the round-trip.
    """
    ids = list(entity_ids)
    if not ids:
        return {}
    rows = db.scalars(
        select(ArtOverride).where(
            ArtOverride.entity_kind == entity_kind,
            ArtOverride.role == role,
            ArtOverride.entity_id.in_(ids),
        )
    ).all()
    return {
        row.entity_id: (
            f"/api/art/{row.entity_kind}/{row.entity_id}/{row.role}"
            f"?v={int(row.set_at.timestamp())}"
        )
        for row in rows
    }


# ---------------------------------------------------------------------------
# Write path: upload + URL fetch
# ---------------------------------------------------------------------------
def save_upload_bytes(
    db: Session,
    *,
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
    data: bytes,
    set_by_user_id: uuid.UUID,
    source_kind: str,
    source_ref: Optional[str] = None,
) -> ArtOverride:
    """Decode, validate, and persist an image. Creates or replaces the
    (entity_kind, entity_id, role) override row. Returns the row.

    The caller is responsible for commit — this function does not.
    """
    validate_kind_role(entity_kind, role)
    if len(data) > _MAX_BYTES:
        raise ArtValidationError(
            f"image exceeds {_MAX_BYTES // (1024 * 1024)} MB cap",
            status_code=413,
        )
    if not data:
        raise ArtValidationError("empty image body", status_code=400)

    ext = _decode_and_classify(data)
    rel_path = _relative_path(entity_kind, entity_id, role, ext)
    abs_path = _absolute_path(rel_path)
    _write_atomically(abs_path, data)

    row = db.get(ArtOverride, (entity_kind, entity_id, role))
    if row is None:
        row = ArtOverride(
            entity_kind=entity_kind,
            entity_id=entity_id,
            role=role,
            local_path=rel_path,
            source_kind=source_kind,
            source_ref=source_ref,
            set_by=set_by_user_id,
        )
        db.add(row)
    else:
        # If the new upload had a different extension, the previous file
        # stays orphaned on disk. Remove it so we don't accumulate cruft.
        if row.local_path != rel_path:
            _quiet_unlink(_absolute_path(row.local_path))
        row.local_path = rel_path
        row.source_kind = source_kind
        row.source_ref = source_ref
        row.set_by = set_by_user_id
        # set_at is refreshed by the server_default on insert only; bump
        # it explicitly on replace so the cache-bust key changes.
        from datetime import datetime, timezone
        row.set_at = datetime.now(timezone.utc)
    db.flush()
    return row


def fetch_and_save_url(
    db: Session,
    *,
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
    url: str,
    set_by_user_id: uuid.UUID,
    source_kind: str = "url",
) -> ArtOverride:
    """Download an image over HTTP(S) and persist it.

    The body is streamed and aborted the moment it crosses the 10 MB cap, so
    a hostile or fat URL (or a lying Content-Length) can't pull unbounded
    bytes into memory. Redirects are followed manually, at most
    `_MAX_REDIRECTS` hops, with an SSRF check on every hop so the fetch can
    never be steered at a LAN or localhost service.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        raise ArtValidationError("url must be absolute http(s)", status_code=400)

    # Wikimedia + several image CDNs reject default httpx UA. Send a real
    # identifier. Accept nudges servers that content-negotiate on it.
    headers = {
        "user-agent": (
            f"F7FIVE0-Art/1.0 (+{PROJECT_URL}; admin art override)"
        ),
        "accept": "image/jpeg,image/png,image/webp,image/*;q=0.8,*/*;q=0.5",
    }
    body = bytearray()
    cap_exceeded = ArtValidationError(
        f"image exceeds {_MAX_BYTES // (1024 * 1024)} MB cap", status_code=413,
    )
    try:
        with httpx.Client(
            timeout=_URL_TIMEOUT,
            follow_redirects=False,
            headers=headers,
        ) as client:
            current = url
            for _hop in range(_MAX_REDIRECTS + 1):
                _assert_public_host(current)
                with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise ArtValidationError(
                                "redirect without a location header",
                                status_code=502,
                            )
                        current = urljoin(current, loc)
                        if not current.lower().startswith(("http://", "https://")):
                            raise ArtValidationError(
                                "redirect to a non-http(s) target",
                                status_code=400,
                            )
                        continue
                    if resp.status_code >= 400:
                        raise ArtValidationError(
                            f"upstream returned HTTP {resp.status_code} for {url}",
                            status_code=502,
                        )
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_BYTES:
                            raise cap_exceeded
                    break
            else:
                raise ArtValidationError("too many redirects", status_code=502)
    except httpx.HTTPError as exc:
        # Surface the exception class + message so the admin sees something
        # actionable in the modal rather than a flat "fetch failed".
        raise ArtValidationError(
            f"fetch failed ({type(exc).__name__}): {exc}",
            status_code=502,
        )

    return save_upload_bytes(
        db,
        entity_kind=entity_kind,
        entity_id=entity_id,
        role=role,
        data=bytes(body),
        set_by_user_id=set_by_user_id,
        source_kind=source_kind,
        source_ref=url,
    )


# ---------------------------------------------------------------------------
# Sync write path
# ---------------------------------------------------------------------------
def _pick_arr_image_url(
    images: Iterable[dict], cover_type: str,
    arr_base_url: str = "", arr_api_key: str = "",
) -> Optional[str]:
    """Pull the best URL for `cover_type` out of an *arr `images` array.

    Prefers `remoteUrl` (the upstream CDN). Falls back to `url` only when
    it is an absolute http(s) URL. As a last resort, if `arr_base_url` is
    provided, constructs a fetchable URL from the *arr's own server +
    the relative `url` path (e.g. `/MediaCover/Artists/123/poster.jpg`),
    appending the API key so the *arr authenticates the request.
    Returns None when no usable URL is present for the requested cover
    type.
    """
    target = cover_type.lower()
    base = arr_base_url.rstrip("/") if arr_base_url else ""
    for img in images or []:
        if (img.get("coverType") or "").lower() != target:
            continue
        remote = img.get("remoteUrl")
        if isinstance(remote, str) and remote.lower().startswith(("http://", "https://")):
            return remote
        local = img.get("url")
        if isinstance(local, str) and local.lower().startswith(("http://", "https://")):
            return local
        # Relative path served by the *arr itself (e.g. /MediaCover/...).
        # Construct a full URL with the API key so fetch_and_save_url can
        # authenticate against the *arr's web server.
        if base and isinstance(local, str) and local.startswith("/"):
            sep = "&" if "?" in local else "?"
            key_param = f"{sep}apikey={arr_api_key}" if arr_api_key else ""
            return f"{base}{local}{key_param}"
        return None
    return None


def download_art_on_sync(
    db: Session,
    *,
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
    images: Iterable[dict],
    cover_type: str,
    source_kind: str,
    arr_base_url: str = "",
    arr_api_key: str = "",
) -> Optional[ArtOverride]:
    """Download an *arr-supplied image into the local art cache.

    Extracts the best URL for `cover_type` from the *arr `images`
    payload, then writes (or refreshes) the art_overrides row for
    `(entity_kind, entity_id, role)`. Returns the override row, or None
    when no usable URL exists or the existing override should be kept.

    Skip rules:
        - No usable URL: return None.
        - Existing override with a non-*arr source_kind (upload / url /
          fanart / musicbrainz / etc.): admin wins, never clobber.
        - Existing override with matching source_ref: already downloaded
          the same URL, nothing to do.
    """
    validate_kind_role(entity_kind, role)
    url = _pick_arr_image_url(images, cover_type, arr_base_url, arr_api_key)
    if url is None:
        return None

    existing = db.get(ArtOverride, (entity_kind, entity_id, role))
    if existing is not None:
        # Admin-set overrides always win. Only refresh when the existing
        # row was previously written by an *arr sync.
        if existing.source_kind not in _ARR_SOURCE_KINDS:
            return None
        if existing.source_ref == url:
            return existing

    try:
        return fetch_and_save_url(
            db,
            entity_kind=entity_kind,
            entity_id=entity_id,
            role=role,
            url=url,
            set_by_user_id=SYSTEM_USER_ID,
            source_kind=source_kind,
        )
    except ArtValidationError as exc:
        # *arr CDNs go flaky, return HTML error pages, redirect to login
        # walls, etc. None of that should crash the sync; leave whatever
        # was there (placeholder if nothing) and try again next pass.
        log.warning(
            "art download skipped: entity=%s/%s role=%s url=%s reason=%s",
            entity_kind, entity_id, role, url, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Delete path
# ---------------------------------------------------------------------------
def clear_override(
    db: Session,
    *,
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
) -> bool:
    """Delete the override row and its on-disk file. Returns True if an
    override existed, False if there was nothing to clear. Caller commits."""
    row = db.get(ArtOverride, (entity_kind, entity_id, role))
    if row is None:
        return False
    _quiet_unlink(_absolute_path(row.local_path))
    db.delete(row)
    db.flush()
    return True


# ---------------------------------------------------------------------------
# File serving path
# ---------------------------------------------------------------------------
def local_file_path(
    db: Session,
    *,
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
) -> Optional[Path]:
    """Resolve the override row to an absolute filesystem path the
    `/art/*` endpoint can stream. Returns None if no override exists
    or the file is missing on disk."""
    row = db.get(ArtOverride, (entity_kind, entity_id, role))
    if row is None:
        return None
    path = _absolute_path(row.local_path)
    if not path.is_file():
        return None
    return path


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _decode_and_classify(data: bytes) -> str:
    """Open the bytes through Pillow, confirm the format is allowed,
    return the canonical file extension. Raises ArtValidationError with
    a 415 if the format isn't one we accept."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            # `img.format` is populated during open(); `verify()` is
            # destructive, so call it last.
            fmt = (img.format or "").upper()
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ArtValidationError(
            f"image decode failed: {exc}", status_code=400,
        )
    ext = _ALLOWED_FORMATS.get(fmt)
    if not ext:
        raise ArtValidationError(
            f"unsupported image format: {fmt or 'unknown'}",
            status_code=415,
        )
    return ext


def _relative_path(
    entity_kind: str, entity_id: uuid.UUID, role: str, ext: str,
) -> str:
    """Relative path inside art_root. Uses forward slashes in the
    stored value; os.path.join rewrites to the platform separator when
    we hit disk via _absolute_path."""
    return f"{entity_kind}/{entity_id}/{role}.{ext}"


def _absolute_path(relative: str) -> Path:
    # Path handles both separators, so a stored "artist/<uuid>/thumb.jpg"
    # resolves on Windows too.
    return Path(settings.art_root) / relative


def _write_atomically(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".art-", suffix=".tmp", dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, target)
    except Exception:
        _quiet_unlink(Path(tmp_name))
        raise


def _quiet_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.warning("failed to unlink %s", path, exc_info=True)
