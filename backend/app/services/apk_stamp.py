"""Stamp data into a signed APK without re-signing it.

An APK signed with scheme v2 or newer has an "APK Signing Block" between the
last zip entry and the central directory. The block is a list of ID-value
pairs. The v2/v3 signatures cover the zip entries, the central directory and
the end-of-central-directory record (EOCD), but not the block itself, and
Android ignores pair IDs it does not know. So a server can add one pair,
shift the central directory to make room, and patch the central directory
offset in the EOCD. The signature digests read that offset as "start of the
signing block", which does not move, so the signature still verifies and the
APK installs (and updates) as the same signed app.

apksigner pads the block to a multiple of 4096 bytes with a verity padding
pair. The padding is rebuilt here so the alignment is kept.

The app reads the pair back from its own installed APK (see
mobile/modules/f7five0-stamp). Nothing here holds the whole APK in memory: a
plan is three parts, the untouched prefix of the original file, the new
block, and the central directory + EOCD.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

STAMP_ID = 0x46374635  # "F7F5"
_PADDING_ID = 0x42726577
_MAGIC = b"APK Sig Block 42"
_EOCD_SIG = 0x06054B50
_PAGE = 4096
MAX_STAMP_BYTES = 8192


class ApkStampError(ValueError):
    """The file is not a v2+ signed APK this module can stamp."""


@dataclass(frozen=True)
class _Layout:
    size: int
    block_start: int
    cd_offset: int
    eocd_rel: int  # EOCD position relative to cd_offset
    pairs: list[tuple[int, bytes]]
    cd_and_eocd: bytes


@dataclass(frozen=True)
class StampPlan:
    path: Path
    prefix_end: int
    block: bytes
    tail: bytes

    @property
    def length(self) -> int:
        return self.prefix_end + len(self.block) + len(self.tail)

    def iter_bytes(self, chunk: int = 1024 * 1024) -> Iterator[bytes]:
        with self.path.open("rb") as fh:
            left = self.prefix_end
            while left > 0:
                data = fh.read(min(chunk, left))
                if not data:
                    raise ApkStampError("APK changed while it was being sent")
                left -= len(data)
                yield data
        yield self.block
        yield self.tail


def _read_at(fh, pos: int, length: int) -> bytes:
    fh.seek(pos)
    data = fh.read(length)
    if len(data) != length:
        raise ApkStampError("short read")
    return data


def _layout(path: Path) -> _Layout:
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        if size < 22:
            raise ApkStampError("not a zip file")
        tail_len = min(size, 22 + 0xFFFF)
        tail = _read_at(fh, size - tail_len, tail_len)
        eocd = -1
        for i in range(tail_len - 22, -1, -1):
            if struct.unpack_from("<I", tail, i)[0] == _EOCD_SIG:
                comment_len = struct.unpack_from("<H", tail, i + 20)[0]
                if i + 22 + comment_len == tail_len:
                    eocd = size - tail_len + i
                    break
        if eocd < 0:
            raise ApkStampError("not a zip file (no end of central directory)")
        cd_offset = struct.unpack_from("<I", tail, eocd - (size - tail_len) + 16)[0]
        if cd_offset == 0xFFFFFFFF:
            raise ApkStampError("zip64 APKs are not supported")
        if cd_offset < 32 or cd_offset > eocd:
            raise ApkStampError("bad central directory offset")
        footer = _read_at(fh, cd_offset - 24, 24)
        if footer[8:] != _MAGIC:
            raise ApkStampError("APK has no v2/v3 signing block")
        block_size = struct.unpack_from("<Q", footer, 0)[0]  # excludes the leading size field
        block_start = cd_offset - block_size - 8
        if block_start < 0:
            raise ApkStampError("bad signing block size")
        block = _read_at(fh, block_start, block_size + 8)
        if struct.unpack_from("<Q", block, 0)[0] != block_size:
            raise ApkStampError("signing block sizes disagree")
        pairs: list[tuple[int, bytes]] = []
        p, end = 8, len(block) - 24
        while p < end:
            if p + 12 > end:
                raise ApkStampError("malformed signing block")
            length = struct.unpack_from("<Q", block, p)[0]
            if length < 4 or p + 8 + length > end:
                raise ApkStampError("malformed signing block")
            pair_id = struct.unpack_from("<I", block, p + 8)[0]
            pairs.append((pair_id, block[p + 12 : p + 8 + length]))
            p += 8 + length
        if p != end:
            raise ApkStampError("malformed signing block")
        cd_and_eocd = _read_at(fh, cd_offset, size - cd_offset)
    return _Layout(size, block_start, cd_offset, eocd - cd_offset, pairs, cd_and_eocd)


def _build_block(pairs: list[tuple[int, bytes]]) -> bytes:
    body = b"".join(struct.pack("<QI", len(v) + 4, i) + v for i, v in pairs)
    # Same rule as apksig: 8 (size) + pairs + 8 (size) + 16 (magic), padded
    # to a whole page with a verity padding pair of at least 12 bytes.
    total = 8 + len(body) + 24
    if total % _PAGE:
        pad = _PAGE - total % _PAGE
        if pad < 12:
            pad += _PAGE
        body += struct.pack("<QI", pad - 8, _PADDING_ID) + b"\0" * (pad - 12)
        total += pad
    size = struct.pack("<Q", total - 8)
    return size + body + size + _MAGIC


def plan_stamp(path: Path, info: dict) -> StampPlan:
    """Plan a copy of `path` carrying `info` (JSON) in the signing block.
    Replaces an earlier stamp if there is one."""
    value = json.dumps(info, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(value) > MAX_STAMP_BYTES:
        raise ApkStampError("stamp too large")
    lay = _layout(path)
    kept = [(i, v) for i, v in lay.pairs if i not in (_PADDING_ID, STAMP_ID)]
    block = _build_block(kept + [(STAMP_ID, value)])
    tail = bytearray(lay.cd_and_eocd)
    struct.pack_into("<I", tail, lay.eocd_rel + 16, lay.block_start + len(block))
    return StampPlan(path=path, prefix_end=lay.block_start, block=block, tail=bytes(tail))


def read_stamp(path: Path) -> Optional[dict]:
    """The stamp in an APK, or None when it has none."""
    for pair_id, value in _layout(path).pairs:
        if pair_id == STAMP_ID:
            return json.loads(value.decode("utf-8"))
    return None
