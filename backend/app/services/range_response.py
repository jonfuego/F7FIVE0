"""HTTP byte-range response helper.

FastAPI/Starlette's FileResponse does not parse `Range:` headers. Video
clients absolutely need it. This helper returns a 206 Partial Content
StreamingResponse when a Range header is present, a plain 200 otherwise.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse


_CHUNK_SIZE = 1024 * 1024  # 1 MiB per yield. Balance between memcopy cost and latency.


def _parse_range(header: str, file_size: int) -> tuple[int, int]:
    """Parse `bytes=START-END`. Returns (start, end) inclusive.

    Only single-range requests are supported; multipart/byteranges is fringe
    for video playback and rejected as 416.
    """
    if not header.lower().startswith("bytes="):
        raise HTTPException(status_code=416, detail="unsupported_range_unit")
    spec = header.split("=", 1)[1].strip()
    if "," in spec:
        raise HTTPException(status_code=416, detail="multipart_ranges_unsupported")
    if "-" not in spec:
        raise HTTPException(status_code=416, detail="invalid_range")
    start_s, end_s = spec.split("-", 1)
    if start_s == "" and end_s == "":
        raise HTTPException(status_code=416, detail="invalid_range")
    if start_s == "":
        # Suffix range: last N bytes
        try:
            suffix = int(end_s)
        except ValueError:
            raise HTTPException(status_code=416, detail="invalid_range")
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="invalid_range")
        start = max(file_size - suffix, 0)
        end = file_size - 1
    else:
        try:
            start = int(start_s)
        except ValueError:
            raise HTTPException(status_code=416, detail="invalid_range")
        if end_s == "":
            end = file_size - 1
        else:
            try:
                end = int(end_s)
            except ValueError:
                raise HTTPException(status_code=416, detail="invalid_range")
    if start < 0 or end < start or start >= file_size:
        raise HTTPException(
            status_code=416,
            detail="range_not_satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    end = min(end, file_size - 1)
    return start, end


async def _stream_file(path: Path, start: int, end: int) -> AsyncGenerator[bytes, None]:
    """Yield `[start, end]` inclusive in chunks. Uses anyio for non-blocking IO."""
    remaining = end - start + 1
    async with await anyio.open_file(path, "rb") as f:
        await f.seek(start)
        while remaining > 0:
            chunk = await f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def serve_file_range(
    path: Path,
    range_header: Optional[str],
    content_type: Optional[str] = None,
) -> StreamingResponse:
    """Serve `path` respecting a Range header. Path must already be resolved
    and validated against its root — this helper does no path auth.
    """
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file_not_found_on_disk")

    file_size = path.stat().st_size
    ct = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    if range_header:
        start, end = _parse_range(range_header, file_size)
        length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            # Allow the CDN to cache segments by URL. Direct-play of full
            # files is private; transcoded segments set their own headers.
            "Cache-Control": "private, max-age=0, no-transform",
        }
        return StreamingResponse(
            _stream_file(path, start, end),
            status_code=206,
            media_type=ct,
            headers=headers,
        )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": "private, max-age=0, no-transform",
    }
    return StreamingResponse(
        _stream_file(path, 0, file_size - 1),
        status_code=200,
        media_type=ct,
        headers=headers,
    )


def ensure_under_roots(path: Path, roots: list[Path]) -> Path:
    """Resolve `path` and fail loudly if it escapes every library root.

    Prevents a signed-URL forgery that tricks the gateway into reading
    arbitrary files. Rejects symlinks that point outside the allow-list too.
    """
    resolved = path.resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root.resolve(strict=False))
            return resolved
        except ValueError:
            continue
    raise HTTPException(status_code=403, detail="path_outside_library_roots")
