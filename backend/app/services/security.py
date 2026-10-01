"""Password hashing, JWT access tokens, refresh token handling, and stream URL signing.

All secrets come from `settings`. No hard-coded keys.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import bcrypt
import jwt

from app.config import settings


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
# bcrypt rejects inputs longer than 72 bytes. We pre-hash with SHA-256 and
# base64-encode (44 bytes, well within the limit) so any-length password is
# safe. This is the same pattern Django uses for its bcrypt_sha256 hasher.
def _prehash(plaintext: str) -> bytes:
    digest = hashlib.sha256(plaintext.encode("utf-8")).digest()
    return base64.b64encode(digest)  # 44 bytes


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(_prehash(plaintext), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plaintext), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Access tokens (short-lived JWT)
# ---------------------------------------------------------------------------
_ALG = "HS256"


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    session_id: uuid.UUID,
    ttl_minutes: Optional[int] = None,
) -> str:
    now = datetime.now(timezone.utc)
    ttl = ttl_minutes if ttl_minutes is not None else settings.jwt_access_ttl_minutes
    payload = {
        "sub": str(user_id),
        "role": role,
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALG)


def decode_access_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError subclasses on failure."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALG])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# ---------------------------------------------------------------------------
# Refresh tokens (opaque random string, hash stored server-side)
# ---------------------------------------------------------------------------
def generate_refresh_token() -> str:
    """URL-safe opaque token. Never store this — store its hash."""
    return secrets.token_urlsafe(48)  # ~64 chars


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex. bcrypt is overkill for a server-generated random; sha256 is fine."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Effectively-persistent refresh TTL for installed PWAs. Browser sessions
# stay on the configured 30-day sliding window; PWA shells get this so the
# home-screen icon never re-prompts for credentials.
PWA_REFRESH_DAYS = 3650  # ~10 years

# Native clients (phones and TVs) use a 90-day *sliding* window: every
# successful refresh issues a new token with a fresh 90-day expiry, so a
# device only has to reconnect once every 90 days to stay signed in. This
# covers TVs that go unused for weeks. The access-token TTL is unchanged
# (15 min). Browser (30d) and PWA behavior are untouched.
NATIVE_REFRESH_DAYS = 90


def refresh_days_for(client_type: str) -> int:
    """Refresh-token lifetime in days for a client type.

    browser -> configured jwt_refresh_ttl_days (30 by default)
    pwa     -> PWA_REFRESH_DAYS (effectively permanent)
    native  -> NATIVE_REFRESH_DAYS (90-day sliding; re-stamped every refresh)
    """
    if client_type == "pwa":
        return PWA_REFRESH_DAYS
    if client_type == "native":
        return NATIVE_REFRESH_DAYS
    return settings.jwt_refresh_ttl_days


def refresh_expires_at(client_type: str = "browser") -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=refresh_days_for(client_type))


# ---------------------------------------------------------------------------
# Stream URL signing (HMAC-SHA256)
# ---------------------------------------------------------------------------
# `offset_bucket` is part of the HMAC payload so a signed URL for a bucket=0
# session can't be trivially retargeted at bucket=2710 by a client. Bucket=0
# (the default) keeps the HMAC input in the same shape as pre-resume URLs
# were intended to use; any URL issued before this change has a different
# payload and will fail verification, which is the desired behavior on
# rolling restart (clients refresh the page to get a new URL).
def _stream_payload(uid: str, mid: str, exp: int, offset_bucket: int,
                    opts: str = "") -> str:
    """HMAC payload for a stream URL. The track-options token (`o`) is appended
    only when present, so option-less URLs sign exactly as they always have."""
    base = f"{uid}:{mid}:{exp}:{offset_bucket}"
    return f"{base}:{opts}" if opts else base


def sign_stream_url_params(user_id: uuid.UUID, media_file_id: uuid.UUID,
                           ttl_hours: Optional[int] = None,
                           offset_bucket: int = 0,
                           opts: str = "") -> dict:
    """Return a dict of query params the Stream Gateway validates.

    Callers attach these to playback URLs. Gateway recomputes the sig and
    compares in constant time. `offset_bucket` is the quantized seek offset
    in seconds (see `OFFSET_BUCKET_SEC` in app.api.stream). Direct-play
    callers pass 0; HLS callers pass the bucketed resume point.
    """
    hours = ttl_hours if ttl_hours is not None else settings.stream_url_ttl_hours
    exp = int((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp())
    payload = _stream_payload(str(user_id), str(media_file_id), exp, offset_bucket, opts)
    sig = hmac.new(
        settings.stream_hmac_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params = {
        "uid": str(user_id),
        "mid": str(media_file_id),
        "exp": exp,
        "sig": sig,
        "t": offset_bucket,
    }
    if opts:
        params["o"] = opts
    return params


def verify_stream_url_params(uid: str, mid: str, exp: int, sig: str,
                             offset_bucket: int = 0, opts: str = "") -> bool:
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return False
    payload = _stream_payload(uid, mid, exp, offset_bucket, opts)
    expected = hmac.new(
        settings.stream_hmac_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


# ---------------------------------------------------------------------------
# Art URL signing (HMAC-SHA256)
# ---------------------------------------------------------------------------
# Android's media-notification artwork loader can't attach a bearer header, so
# the app needs a short-lived signed URL it can hand to the OS. The signature
# binds the full art path (entity_kind/entity_id/role) plus the expiry, so a
# signature minted for one image can't be replayed against a different one. The
# user id is part of the payload too so a link is attributable, but reuses the
# same `stream_hmac_secret` as the stream signer since both are the same class
# of short-lived, HMAC-gated, header-free URL. Verification is constant-time.
def sign_art_url_params(entity_kind: str, entity_id: uuid.UUID, role: str,
                        user_id: uuid.UUID,
                        ttl_hours: Optional[int] = None) -> dict:
    """Return the query params the /api/art read endpoint validates.

    Callers attach these to an art URL so a header-less client (the Android
    media notification) can load the image. The endpoint recomputes the sig
    over the same path + exp and compares in constant time.
    """
    hours = ttl_hours if ttl_hours is not None else settings.stream_url_ttl_hours
    exp = int((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp())
    payload = f"{entity_kind}:{entity_id}:{role}:{user_id}:{exp}"
    sig = hmac.new(
        settings.stream_hmac_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "uid": str(user_id),
        "exp": exp,
        "sig": sig,
    }


def verify_art_url_params(entity_kind: str, entity_id: uuid.UUID, role: str,
                          uid: str, exp: int, sig: str) -> bool:
    """Constant-time check of an art signature. False on expiry or tamper.

    The path (entity_kind/entity_id/role) is passed straight from the request
    so the signature is bound to the image it was minted for; a valid sig for a
    different image fails here.
    """
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return False
    payload = f"{entity_kind}:{entity_id}:{role}:{uid}:{exp}"
    expected = hmac.new(
        settings.stream_hmac_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


def build_signed_art_url(base: str, entity_kind: str, entity_id: uuid.UUID,
                         role: str, user_id: uuid.UUID,
                         ttl_hours: Optional[int] = None) -> str:
    """Mint an absolute, signed art URL a header-less client can load.

    `base` is the origin (e.g. "https://media.example.com"); a trailing
    slash is tolerated. Returns
    `{base}/api/art/{kind}/{id}/{role}?uid=...&exp=...&sig=...`.
    """
    params = sign_art_url_params(
        entity_kind, entity_id, role, user_id, ttl_hours=ttl_hours,
    )
    query = urlencode(params)
    root = base.rstrip("/")
    return f"{root}/api/art/{entity_kind}/{entity_id}/{role}?{query}"


# ---------------------------------------------------------------------------
# General media URL signing (subtitles + downloads)
# ---------------------------------------------------------------------------
# Subtitle sidecars (WebVTT extracted from a media file) and offline downloads
# both need a header-less signed URL so the native player / OS downloader can
# fetch them without a bearer, exactly like art. The signature binds the
# media_file_id, the action ("subtitle" | "download"), and a per-action `extra`
# discriminator (the subtitle stream index, or the requested download quality)
# so a signature minted for one subtitle track or one quality cannot be
# replayed against another. Reuses `stream_hmac_secret` (same class of
# short-lived HMAC-gated URL). Verification is constant-time.
def sign_media_url_params(media_file_id: uuid.UUID, action: str, extra: str,
                          user_id: uuid.UUID,
                          ttl_hours: Optional[int] = None) -> dict:
    """Return the query params a signed media endpoint validates.

    `action` is a short verb ("subtitle" / "download"); `extra` discriminates
    within the action (the subtitle stream index as a string, or the download
    quality). Both are folded into the HMAC payload so the signature is bound
    to the exact resource.
    """
    hours = ttl_hours if ttl_hours is not None else settings.stream_url_ttl_hours
    exp = int((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp())
    payload = f"{media_file_id}:{action}:{extra}:{user_id}:{exp}"
    sig = hmac.new(
        settings.stream_hmac_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "uid": str(user_id),
        "exp": exp,
        "sig": sig,
    }


def verify_media_url_params(media_file_id: uuid.UUID, action: str, extra: str,
                            uid: str, exp: int, sig: str) -> bool:
    """Constant-time check of a media signature. False on expiry or tamper.

    The `media_file_id`, `action`, and `extra` come straight from the request
    so a valid signature for a different file / action / stream / quality
    fails here.
    """
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return False
    payload = f"{media_file_id}:{action}:{extra}:{uid}:{exp}"
    expected = hmac.new(
        settings.stream_hmac_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


def build_signed_subtitle_url(base: str, media_file_id: uuid.UUID,
                              stream_index: int, user_id: uuid.UUID,
                              ttl_hours: Optional[int] = None) -> str:
    """Absolute signed WebVTT subtitle URL a header-less player can load.

    Returns
    `{base}/api/media-files/{id}/subtitles/{index}.vtt?uid=...&exp=...&sig=...`.
    """
    params = sign_media_url_params(
        media_file_id, "subtitle", str(stream_index), user_id, ttl_hours=ttl_hours,
    )
    query = urlencode(params)
    root = base.rstrip("/")
    return (
        f"{root}/api/media-files/{media_file_id}/subtitles/"
        f"{stream_index}.vtt?{query}"
    )


def build_signed_download_url(base: str, media_file_id: uuid.UUID,
                              quality: str, user_id: uuid.UUID,
                              ttl_hours: Optional[int] = None) -> str:
    """Absolute signed download URL a header-less downloader can fetch.

    Returns
    `{base}/api/media-files/{id}/download?quality=...&uid=...&exp=...&sig=...`.
    """
    params = sign_media_url_params(
        media_file_id, "download", quality, user_id, ttl_hours=ttl_hours,
    )
    query = urlencode({"quality": quality, **params})
    root = base.rstrip("/")
    return f"{root}/api/media-files/{media_file_id}/download?{query}"
