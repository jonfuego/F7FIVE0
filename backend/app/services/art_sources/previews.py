"""Small preview URLs for the art picker's candidate tiles.

A candidate has two image URLs: `url` is what applying downloads (full size),
`preview_url` is what the tile's `<img>` loads. Previews keep the grid light:
a TMDB poster set at `original` is several MB per tile, a 24-tile grid pulls
well over 50 MB before the admin has picked anything.

Each source builds its own preview where it knows the size scheme, using the
helpers below. `preview_for` is the generic version for URLs that arrive from
somewhere else (the *arr `remoteUrl` entries are mostly TMDB, TheTVDB and
iTunes URLs). It returns the URL unchanged when it does not recognise the
host, so a preview is never a guess that could 404.

When a new art source is added: give its candidates a `preview_url` if the
host offers sizes, or leave it out. The aggregator
(`art_search._ensure_previews`) fills any missing one with `url`.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit


TMDB_IMG_HOST = "image.tmdb.org"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"
# Largest preview sizes the tiles use. Posters and backdrops have different
# size ladders on TMDB (w342 is a poster size, w300 is the small backdrop).
TMDB_POSTER_PREVIEW = "w342"
TMDB_BACKDROP_PREVIEW = "w300"

ITUNES_PREVIEW_SIZE = "300x300bb"
_ITUNES_SIZE_RE = re.compile(r"/\d{2,4}x\d{2,4}bb\.(jpg|png|webp)$")

AUDIODB_PREVIEW_VARIANT = "small"
_AUDIODB_HOST_SUFFIX = "theaudiodb.com"
_AUDIODB_EXT = (".jpg", ".jpeg", ".png")


def tmdb_url(path: str, size: str) -> str:
    """`https://image.tmdb.org/t/p/<size><file_path>` for a TMDB `file_path`."""
    return f"{TMDB_IMG_BASE}/{size}{path}"


def itunes_url(url: str, size: str) -> str:
    """Swap the `<w>x<h>bb` size segment of an Apple artwork URL.

    Returns `url` unchanged when it has no recognisable size segment.
    """
    match = _ITUNES_SIZE_RE.search(url)
    if match is None:
        return url
    return f"{url[:match.start()]}/{size}.{match.group(1)}"


def audiodb_url(url: str, variant: str) -> str:
    """TheAudioDB serves `<image>.jpg/<variant>` (`preview`, `small`,
    `medium`, `large`). Returns `url` unchanged for anything else."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == _AUDIODB_HOST_SUFFIX or host.endswith("." + _AUDIODB_HOST_SUFFIX)):
        return url
    if not parts.path.lower().endswith(_AUDIODB_EXT):
        return url
    return f"{url}/{variant}"


def preview_for(url: str, *, backdrop: bool = False) -> Optional[str]:
    """Best-effort preview for a URL whose source did not build one.

    `backdrop` picks the TMDB backdrop size ladder instead of the poster one.
    Returns None when the host is not one with a known size scheme (the
    caller then shows the URL itself).
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == TMDB_IMG_HOST:
        m = re.match(r"^/t/p/(?:original|w\d+)(/.+)$", parts.path)
        if m is None:
            return None
        size = TMDB_BACKDROP_PREVIEW if backdrop else TMDB_POSTER_PREVIEW
        return tmdb_url(m.group(1), size)
    if host.endswith("mzstatic.com"):
        out = itunes_url(url, ITUNES_PREVIEW_SIZE)
        return out if out != url else None
    return None
