"""Unit tests for the general media URL signing (subtitle + download)."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from app.services import security


def test_sign_verify_roundtrip_subtitle():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "subtitle", "3", uid)
    assert security.verify_media_url_params(
        mid, "subtitle", "3", params["uid"], params["exp"], params["sig"],
    )


def test_sign_verify_roundtrip_download():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "download", "720p", uid)
    assert security.verify_media_url_params(
        mid, "download", "720p", params["uid"], params["exp"], params["sig"],
    )


def test_signature_bound_to_stream_index():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "subtitle", "3", uid)
    # A sig minted for index 3 must not validate for index 4.
    assert not security.verify_media_url_params(
        mid, "subtitle", "4", params["uid"], params["exp"], params["sig"],
    )


def test_signature_bound_to_action():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "subtitle", "3", uid)
    assert not security.verify_media_url_params(
        mid, "download", "3", params["uid"], params["exp"], params["sig"],
    )


def test_signature_bound_to_media_file():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "download", "original", uid)
    other = uuid.uuid4()
    assert not security.verify_media_url_params(
        other, "download", "original", params["uid"], params["exp"], params["sig"],
    )


def test_expired_signature_rejected():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "download", "original", uid, ttl_hours=1)
    past = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
    # Re-sign with an expired exp by tampering: verification must fail on exp.
    assert not security.verify_media_url_params(
        mid, "download", "original", params["uid"], past, params["sig"],
    )


def test_tampered_sig_rejected():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    params = security.sign_media_url_params(mid, "download", "original", uid)
    assert not security.verify_media_url_params(
        mid, "download", "original", params["uid"], params["exp"], "deadbeef",
    )


def test_build_signed_subtitle_url_shape():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    url = security.build_signed_subtitle_url("https://x.example/", mid, 3, uid)
    assert url.startswith(f"https://x.example/api/media-files/{mid}/subtitles/3.vtt?")
    assert "uid=" in url and "exp=" in url and "sig=" in url


def test_build_signed_download_url_shape():
    mid = uuid.uuid4()
    uid = uuid.uuid4()
    url = security.build_signed_download_url("https://x.example", mid, "720p", uid)
    assert url.startswith(f"https://x.example/api/media-files/{mid}/download?")
    assert "quality=720p" in url
    assert "uid=" in url and "exp=" in url and "sig=" in url
