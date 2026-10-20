"""Tests for services/tag_writer.py.

Uses minimal valid audio bytes for each format, constructed in-process so no
external audio tools are required.
"""
from __future__ import annotations

import os
import struct
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Minimal valid audio file builders
# ---------------------------------------------------------------------------

def _make_mp3(path: str) -> None:
    """Write a minimal MP3: an ID3v2.3 header followed by two MPEG frames
    so mutagen's frame-sync validation accepts the file."""
    from mutagen import id3

    tags = id3.ID3()
    tags.save(path, v2_version=3)

    # MPEG1 Layer3 128kbps 44100Hz stereo -- 417-byte frame
    frame = bytes([0xFF, 0xFB, 0x90, 0x04]) + bytes(413)
    with open(path, "ab") as f:
        f.write(frame + frame)  # two frames required for sync validation


def _ogg_crc32(data: bytes) -> int:
    """OGG Vorbis CRC32 (polynomial 0x04c11db7, non-standard)."""
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = (crc << 1) ^ 0x04c11db7
            else:
                crc <<= 1
            crc &= 0xFFFFFFFF
    return crc


def _ogg_page(serial: int, seq: int, granule: int, data: bytes, *, bos: bool = False, eos: bool = False) -> bytes:
    header_type = 0
    if bos:
        header_type |= 0x02
    if eos:
        header_type |= 0x04
    # One segment per page for simplicity
    segment_table = bytes([len(data)])
    n_segs = 1
    page = (
        b"OggS"                          # capture pattern
        + bytes([0])                     # version
        + bytes([header_type])           # header type
        + struct.pack("<q", granule)     # granule position
        + struct.pack("<I", serial)      # bitstream serial
        + struct.pack("<I", seq)         # page sequence
        + b"\x00\x00\x00\x00"           # checksum placeholder
        + bytes([n_segs])               # number of segments
        + segment_table
        + data
    )
    checksum = _ogg_crc32(page)
    return page[:22] + struct.pack("<I", checksum) + page[26:]


def _make_ogg(path: str) -> None:
    """Write a minimal OGG Vorbis file with 3 pages."""
    serial = 0x12345678

    # Page 1: ID header (BOS)
    id_header = (
        bytes([0x01])           # packet type: identification
        + b"vorbis"
        + struct.pack("<I", 0)  # vorbis version
        + bytes([2])            # channels
        + struct.pack("<I", 44100)  # sample rate
        + struct.pack("<i", -1) + struct.pack("<i", 128000) + struct.pack("<i", -1)
        + bytes([0xB8])         # blocksize
        + bytes([0x01])         # framing
    )

    # Page 2: comment header
    vendor = b"test"
    comment_header = (
        bytes([0x03])           # packet type: comment
        + b"vorbis"
        + struct.pack("<I", len(vendor)) + vendor
        + struct.pack("<I", 0)  # zero user comments
        + bytes([0x01])         # framing
    )

    # Page 3: setup header (EOS for minimal file)
    setup_header = (
        bytes([0x05])           # packet type: setup
        + b"vorbis"
        + bytes([0x00, 0x01])   # minimal setup data
    )

    page1 = _ogg_page(serial, 0, 0, id_header, bos=True)
    page2 = _ogg_page(serial, 1, 0, comment_header)
    page3 = _ogg_page(serial, 2, 0, setup_header, eos=True)

    with open(path, "wb") as f:
        f.write(page1 + page2 + page3)


def _make_flac(path: str) -> None:
    """Write a minimal FLAC file: just the fLaC magic + STREAMINFO block."""
    # STREAMINFO: 34 bytes of data
    # min blocksize=4096, max blocksize=4096, min framesize=0, max framesize=0
    # samplerate=44100, channels=1, bits/sample=16, total_samples=0, md5=0*16
    si = (
        b'\x10\x00'             # min blocksize 4096
        b'\x10\x00'             # max blocksize 4096
        b'\x00\x00\x00'         # min framesize 0
        b'\x00\x00\x00'         # max framesize 0
        # samplerate(20b)=44100=0xAC44, channels(3b)=0 (1ch), bps(5b)=15 (16bit), samples(36b)=0
        b'\x0a\xc4\x40\x0f\x00\x00\x00\x00'
        + b'\x00' * 16          # MD5
    )
    # Last metadata block flag (0x80) | block type 0 (STREAMINFO) = 0x80
    block_header = bytes([0x80, 0x00, 0x00, len(si)])
    with open(path, "wb") as f:
        f.write(b"fLaC" + block_header + si)


def _atom(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data) + 8) + name + data


def _make_m4a(path: str) -> None:
    """Write a minimal M4A: ftyp + moov(mvhd) atoms.

    mvhd version-0 layout (100 bytes of data):
      version(1) + flags(3) + ctime(4) + mtime(4) + timescale(4) + duration(4)
      + rate(4) + volume(2) + reserved(10) + matrix(36) + predefined(24) + next_track(4)
    timescale must be non-zero to avoid division-by-zero in mutagen.
    """
    # Identity matrix for the 36-byte video transformation matrix
    identity = struct.pack(
        ">9i",
        0x00010000, 0, 0,
        0, 0x00010000, 0,
        0, 0, 0x40000000,
    )
    mvhd_data = (
        b"\x00"                         # version 0
        b"\x00\x00\x00"                 # flags
        + struct.pack(">I", 0)          # creation_time
        + struct.pack(">I", 0)          # modification_time
        + struct.pack(">I", 1000)       # time_scale (non-zero!)
        + struct.pack(">I", 0)          # duration
        + struct.pack(">I", 0x00010000) # rate = 1.0
        + struct.pack(">H", 0x0100)     # volume = 1.0
        + b"\x00" * 10                  # reserved
        + identity                      # 36-byte matrix
        + b"\x00" * 24                  # pre_defined
        + struct.pack(">I", 1)          # next_track_ID
    )
    ftyp = _atom(b"ftyp", b"M4A " + struct.pack(">I", 0) + b"M4A ")
    mvhd = _atom(b"mvhd", mvhd_data)
    moov = _atom(b"moov", mvhd)
    with open(path, "wb") as f:
        f.write(ftyp + moov)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write(path: str, tags: dict, profile: dict = None):
    from app.services.tag_writer import write_tags
    return write_tags(path, tags, profile or {})


# ---------------------------------------------------------------------------
# MP3
# ---------------------------------------------------------------------------

def test_write_tags_mp3_v23(tmp_path):
    p = str(tmp_path / "test.mp3")
    _make_mp3(p)
    err = _write(p, {"title": "My Song", "track_number": 3}, {"id3_version": "2.3"})
    assert err is None

    from mutagen import File
    f = File(p, easy=True)
    assert f is not None
    assert f.get("title") == ["My Song"]


def test_write_tags_mp3_v24(tmp_path):
    p = str(tmp_path / "test.mp3")
    _make_mp3(p)
    err = _write(p, {"title": "Song v24", "track_number": 5}, {"id3_version": "2.4"})
    assert err is None

    from mutagen import File
    f = File(p, easy=True)
    assert f.get("title") == ["Song v24"]


def test_write_tags_mp3_readback_track(tmp_path):
    p = str(tmp_path / "track.mp3")
    _make_mp3(p)
    err = _write(p, {"title": "Track Test", "track_number": 7, "album": "Album X"})
    assert err is None

    from mutagen import File
    f = File(p, easy=True)
    assert f.get("title") == ["Track Test"]
    assert f.get("album") == ["Album X"]
    tracknumber = f.get("tracknumber", [""])[0]
    assert "7" in tracknumber


# ---------------------------------------------------------------------------
# FLAC
# ---------------------------------------------------------------------------

def test_write_tags_flac_success(tmp_path):
    p = str(tmp_path / "test.flac")
    _make_flac(p)
    err = _write(p, {"title": "FLAC Song", "track_number": 2})
    assert err is None


def test_write_tags_flac_readback(tmp_path):
    p = str(tmp_path / "readback.flac")
    _make_flac(p)
    err = _write(p, {"title": "Read Back", "track_number": 4, "album_artist": "The Band"})
    assert err is None

    from mutagen import File
    f = File(p, easy=True)
    assert f is not None
    assert f.get("title") == ["Read Back"]
    assert f.get("albumartist") == ["The Band"]


# ---------------------------------------------------------------------------
# OGG
# ---------------------------------------------------------------------------

def test_write_tags_ogg_success(tmp_path):
    p = str(tmp_path / "test.ogg")
    _make_ogg(p)
    err = _write(p, {"title": "OGG Song", "track_number": 1})
    assert err is None


def test_write_tags_ogg_readback(tmp_path):
    p = str(tmp_path / "ogg_read.ogg")
    _make_ogg(p)
    err = _write(p, {"title": "OGG Read", "album": "OGG Album", "track_number": 3})
    assert err is None

    from mutagen import File
    f = File(p, easy=True)
    assert f is not None
    assert f.get("title") == ["OGG Read"]
    assert f.get("album") == ["OGG Album"]


# ---------------------------------------------------------------------------
# M4A
# ---------------------------------------------------------------------------

def test_write_tags_m4a_success(tmp_path):
    p = str(tmp_path / "test.m4a")
    _make_m4a(p)
    err = _write(p, {"title": "M4A Song", "track_number": 8})
    assert err is None


def test_write_tags_m4a_readback(tmp_path):
    p = str(tmp_path / "m4a_read.m4a")
    _make_m4a(p)
    err = _write(p, {"title": "M4A Read", "album": "M4A Album", "track_number": 2})
    assert err is None

    from mutagen import File
    f = File(p)
    assert f is not None
    # M4A tags are stored as bytes; decode title
    title = f.get("\xa9nam")
    assert title is not None


# ---------------------------------------------------------------------------
# Unsupported format
# ---------------------------------------------------------------------------

def test_write_tags_wmv_returns_error_string(tmp_path):
    p = str(tmp_path / "clip.wmv")
    # Do not create the file; the function must not touch it
    result = _write(p, {"title": "WMV"})
    assert result is not None  # non-None = error string
    assert isinstance(result, str)
    assert not os.path.exists(p)  # file was never created


def test_write_tags_unknown_extension_returns_error(tmp_path):
    p = str(tmp_path / "file.xyz")
    result = _write(p, {"title": "XYZ"})
    assert result is not None
    assert "unsupported" in result.lower() or "xyz" in result.lower()


# ---------------------------------------------------------------------------
# backup_tags / restore_tags
# ---------------------------------------------------------------------------

def test_backup_and_restore_mp3(tmp_path):
    from app.services.tag_writer import backup_tags, restore_tags

    p = str(tmp_path / "backup.mp3")
    _make_mp3(p)
    _write(p, {"title": "Before", "track_number": 1})

    backup = backup_tags(p)
    assert backup is not None

    _write(p, {"title": "After", "track_number": 2})

    err = restore_tags(p, backup)
    assert err is None

    from mutagen import File
    f = File(p, easy=True)
    assert f.get("title") == ["Before"]


def test_backup_returns_none_for_unsupported(tmp_path):
    from app.services.tag_writer import backup_tags
    p = str(tmp_path / "file.wmv")
    result = backup_tags(p)
    assert result is None
