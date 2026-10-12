"""What counts as podcast audio, and which file extension it gets.

The relay (`/stream/podcast/...`), server downloads and the episode lists all
ask the same questions: is this response audio, is this enclosure video (listed
but not played), what extension does a file of this type get.
"""
from __future__ import annotations

import posixpath
from typing import Optional
from urllib.parse import urlsplit

# Extensions a publisher's file may carry and the local scan reads.
AUDIO_EXTS = frozenset({"mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "mp4a"})

_EXT_BY_TYPE = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mpeg3": "mp3",
    "audio/x-mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "aac",
    "audio/x-aac": "aac",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}

_TYPE_BY_EXT = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "mp4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
}


def main_type(content_type: Optional[str]) -> str:
    """`audio/mpeg; charset=x` -> `audio/mpeg`."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def url_ext(url: Optional[str]) -> str:
    """The lower-case extension of the URL's path (no query), or ""."""
    if not url:
        return ""
    ext = posixpath.splitext(urlsplit(url).path)[1].lstrip(".").lower()
    return ext


def is_video_type(content_type: Optional[str]) -> bool:
    return main_type(content_type).startswith("video/")


def is_audio_response(content_type: Optional[str], url: Optional[str]) -> bool:
    """A response is playable audio when its type is `audio/*`, or it is a
    generic byte stream (`application/octet-stream`, `binary/octet-stream`)
    for a URL whose path ends in an audio extension."""
    ctype = main_type(content_type)
    if ctype.startswith("audio/"):
        return True
    if ctype in ("application/octet-stream", "binary/octet-stream"):
        return url_ext(url) in AUDIO_EXTS
    return False


def ext_for(content_type: Optional[str], url: Optional[str]) -> str:
    """The extension for a file of this type from this URL: the URL's own when
    it is an audio one, else from the type, else mp3."""
    ext = url_ext(url)
    if ext in AUDIO_EXTS:
        return "m4a" if ext == "mp4a" else ext
    return _EXT_BY_TYPE.get(main_type(content_type), "mp3")


def content_type_for_ext(ext: Optional[str], fallback: str = "audio/mpeg") -> str:
    return _TYPE_BY_EXT.get((ext or "").lower().lstrip("."), fallback)
