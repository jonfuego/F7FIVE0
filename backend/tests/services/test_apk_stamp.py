"""apk_stamp: add server info to a signed APK without touching what the
signature covers."""
from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from app.services import apk_stamp

MAGIC = b"APK Sig Block 42"


def _fake_signed_apk(path: Path, pairs: list[tuple[int, bytes]], pad_to_page: bool = True) -> None:
    """A zip with a v2-style signing block between the entries and the
    central directory. Not a real signature; the layout is what matters."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", b"<manifest/>" * 50)
        z.writestr("classes.dex", bytes(range(256)) * 20)
    raw = buf.getvalue()
    eocd = raw.rfind(b"PK\x05\x06")
    cd = struct.unpack_from("<I", raw, eocd + 16)[0]
    body = b"".join(struct.pack("<QI", len(v) + 4, i) + v for i, v in pairs)
    total = 8 + len(body) + 24
    if pad_to_page and total % 4096:
        pad = 4096 - total % 4096
        if pad < 12:
            pad += 4096
        body += struct.pack("<QI", pad - 8, 0x42726577) + b"\0" * (pad - 12)
        total += pad
    size = struct.pack("<Q", total - 8)
    block = size + body + size + MAGIC
    tail = bytearray(raw[cd:])
    struct.pack_into("<I", tail, eocd - cd + 16, cd + len(block))
    path.write_bytes(raw[:cd] + block + bytes(tail))


def _write(plan: apk_stamp.StampPlan, out: Path) -> bytes:
    data = b"".join(plan.iter_bytes(chunk=1000))
    out.write_bytes(data)
    return data


def _covered_parts(data: bytes) -> tuple[bytes, bytes, bytes]:
    """What v2/v3 digests cover: entries, central directory, and the EOCD
    with its CD offset replaced by the signing block offset."""
    eocd = data.rfind(b"PK\x05\x06")
    cd = struct.unpack_from("<I", data, eocd + 16)[0]
    block_size = struct.unpack_from("<Q", data, cd - 24)[0]
    block_start = cd - block_size - 8
    e = bytearray(data[eocd:])
    struct.pack_into("<I", e, 16, block_start)
    return data[:block_start], data[cd:eocd], bytes(e)


def test_stamp_round_trips_and_keeps_signed_parts(tmp_path):
    src = tmp_path / "app.apk"
    _fake_signed_apk(src, [(0x7109871A, b"signature-v2" * 10), (0x504B4453, b"dep-info")])
    plan = apk_stamp.plan_stamp(src, {"v": 1, "servers": ["https://media.example.com"]})
    out = tmp_path / "stamped.apk"
    data = _write(plan, out)

    assert len(data) == plan.length
    assert apk_stamp.read_stamp(out) == {"v": 1, "servers": ["https://media.example.com"]}
    assert apk_stamp.read_stamp(src) is None
    assert _covered_parts(data) == _covered_parts(src.read_bytes())
    # Other pairs survive, block stays page aligned, zip still opens.
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert z.read("AndroidManifest.xml").startswith(b"<manifest/>")
    block_len = len(plan.block)
    assert block_len % 4096 == 0
    assert b"signature-v2" in plan.block and b"dep-info" in plan.block


def test_restamp_replaces_old_stamp(tmp_path):
    src = tmp_path / "app.apk"
    _fake_signed_apk(src, [(0x7109871A, b"sig")])
    once = tmp_path / "once.apk"
    _write(apk_stamp.plan_stamp(src, {"v": 1, "servers": ["http://a"]}), once)
    twice = tmp_path / "twice.apk"
    _write(apk_stamp.plan_stamp(once, {"v": 1, "servers": ["http://b"]}), twice)
    assert apk_stamp.read_stamp(twice) == {"v": 1, "servers": ["http://b"]}
    assert twice.read_bytes().count(struct.pack("<I", apk_stamp.STAMP_ID)) == 1
    assert _covered_parts(twice.read_bytes()) == _covered_parts(src.read_bytes())


def test_large_stamp_grows_block_by_whole_pages(tmp_path):
    src = tmp_path / "app.apk"
    _fake_signed_apk(src, [(0x7109871A, b"sig")])
    plan = apk_stamp.plan_stamp(src, {"servers": ["https://x.example.com"] * 200})
    assert len(plan.block) % 4096 == 0 and len(plan.block) > 4096


def test_unpadded_block_is_padded(tmp_path):
    src = tmp_path / "app.apk"
    _fake_signed_apk(src, [(0x7109871A, b"sig")], pad_to_page=False)
    plan = apk_stamp.plan_stamp(src, {"v": 1})
    assert len(plan.block) % 4096 == 0


def test_rejects_unsigned_zip_and_junk(tmp_path):
    plain = tmp_path / "plain.apk"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("a.txt", "hi")
    with pytest.raises(apk_stamp.ApkStampError):
        apk_stamp.plan_stamp(plain, {"v": 1})
    junk = tmp_path / "junk.apk"
    junk.write_bytes(b"not a zip at all" * 10)
    with pytest.raises(apk_stamp.ApkStampError):
        apk_stamp.plan_stamp(junk, {"v": 1})


def test_rejects_oversized_stamp(tmp_path):
    src = tmp_path / "app.apk"
    _fake_signed_apk(src, [(0x7109871A, b"sig")])
    with pytest.raises(apk_stamp.ApkStampError):
        apk_stamp.plan_stamp(src, {"x": "y" * (apk_stamp.MAX_STAMP_BYTES + 1)})


def test_real_release_apk_if_present(tmp_path):
    """Runs against mobile/dist when a built APK is there (local only)."""
    dist = Path(__file__).resolve().parents[3] / "mobile" / "dist"
    apks = sorted(p for p in dist.glob("F7FIVE0-*.apk") if "stamped" not in p.name) if dist.exists() else []
    if not apks:
        pytest.skip("no APK in mobile/dist")
    src = apks[0]
    plan = apk_stamp.plan_stamp(src, {"v": 1, "servers": ["https://media.example.com"]})
    out = tmp_path / "real.apk"
    data = _write(plan, out)
    assert apk_stamp.read_stamp(out)["servers"] == ["https://media.example.com"]
    assert _covered_parts(data) == _covered_parts(src.read_bytes())
