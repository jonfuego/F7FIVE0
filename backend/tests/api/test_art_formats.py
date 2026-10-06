"""SEC-P0-1: the art decode path accepts only JPEG/PNG/WEBP and enforces it
with an explicit Pillow ``formats=`` allowlist, so a non-allowed format can
never reach a vulnerable parser even though we ultimately store only those
three. Every art upload path (admin upload, paste-URL, *arr search import,
scan import) funnels through ``_decode_and_classify`` / ``save_upload_bytes``,
so a rejection there is a rejection everywhere.
"""
import io
import uuid

import pytest
from PIL import Image

from app.models.art import ArtOverride, ENTITY_ALBUM, ROLE_COVER
from app.services import art as art_service


def _img_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, fmt)
    return buf.getvalue()


def test_decode_gate_rejects_valid_gif():
    """A byte-valid GIF is refused at the shared decode gate. With the
    allowlist Pillow will not even select the GIF parser."""
    gif = _img_bytes("GIF")
    assert gif[:3] == b"GIF"
    with pytest.raises(art_service.ArtValidationError) as ei:
        art_service._decode_and_classify(gif)
    assert ei.value.status_code in (400, 415)


def test_decode_gate_rejects_other_non_allowed_format():
    """BMP is a format Pillow can normally decode; the allowlist still
    refuses it, proving this is an allowlist and not a GIF-specific block."""
    bmp = _img_bytes("BMP")
    with pytest.raises(art_service.ArtValidationError):
        art_service._decode_and_classify(bmp)


def test_decode_gate_accepts_allowed_formats():
    """The three accepted formats still classify to their stored extension,
    so the allowlist is not over-broad."""
    assert art_service._decode_and_classify(_img_bytes("PNG")) == "png"
    assert art_service._decode_and_classify(_img_bytes("JPEG")) == "jpg"
    assert art_service._decode_and_classify(_img_bytes("WEBP")) == "webp"


def test_save_upload_bytes_rejects_gif_before_persisting(db_session):
    """The shared write helper (used by the upload endpoint, paste-URL fetch,
    and scan imports) rejects a GIF and persists nothing."""
    with pytest.raises(art_service.ArtValidationError):
        art_service.save_upload_bytes(
            db_session,
            entity_kind=ENTITY_ALBUM,
            entity_id=uuid.uuid4(),
            role=ROLE_COVER,
            data=_img_bytes("GIF"),
            set_by_user_id=uuid.uuid4(),
            source_kind="upload",
        )
    assert db_session.query(ArtOverride).count() == 0


def test_upload_endpoint_rejects_gif(client):
    """The admin art upload endpoint returns a 4xx for a GIF."""
    r = client.post(
        f"/api/admin/art/{ENTITY_ALBUM}/{uuid.uuid4()}/{ROLE_COVER}",
        files={"file": ("cover.gif", _img_bytes("GIF"), "image/gif")},
    )
    assert r.status_code in (400, 415), r.text
