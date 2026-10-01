"""Path rewriting at the *arr sync boundary.

Radarr and Lidarr report paths on drive letters that are only visible to the
interactive user session that mapped them (e.g. `N:` mapped to a NAS share).
Services running as LocalSystem or any non-interactive account cannot see
those drive letters, so ffprobe and os.path.exists fail and every row ends
up marked `missing`.

Fix: rewrite drive-letter prefixes to the underlying UNC path once, at the
point where the *arr payload hits our DB. Paths are stored canonically as
UNC from then on, which every service account can resolve as long as the
account has credentials to the share (run the services under a user account
that has the share saved in Credential Manager).

Rules are loaded from settings.path_rewrite_rules, a semicolon-delimited
string of `SRC=DST` pairs. Example:

    PATH_REWRITE_RULES=N:=\\\\nas\\media

A leading/trailing backslash on either side is normalized away so you can't
double-slash by accident. Empty string means no rewriting.
"""
from __future__ import annotations

from typing import Iterable

from app.config import settings


def _parse_rules(raw: str) -> list[tuple[str, str]]:
    """Parse `SRC=DST;SRC=DST` into a list of (src, dst) tuples.

    Both sides are stripped of whitespace and trailing backslashes so that
    `N:` and `N:\\` produce the same rule, and `\\\\host\\share\\` and
    `\\\\host\\share` do too.
    """
    rules: list[tuple[str, str]] = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        src, dst = part.split("=", 1)
        src = src.strip().rstrip("\\")
        dst = dst.strip().rstrip("\\")
        if not src or not dst:
            continue
        rules.append((src, dst))
    return rules


_RULES_CACHE: list[tuple[str, str]] | None = None


def _rules() -> list[tuple[str, str]]:
    """Load and cache rules on first call. Settings are frozen at process
    start so a single read is sufficient."""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = _parse_rules(settings.path_rewrite_rules)
    return _RULES_CACHE


def translate(path: str | None) -> str | None:
    """Rewrite `path` according to the configured rules.

    Matching is case-insensitive on the source prefix so `N:\\...` and
    `n:\\...` both match. The separator between source and remainder is
    preserved exactly so we don't corrupt the path.

    Returns the input unchanged if no rule matches or if rewriting is
    disabled. Returns None for None input so callers can pass-through.
    """
    if not path:
        return path
    for src, dst in _rules():
        # Match a drive-letter-style prefix `X:` followed by `\` or `/`, or
        # a UNC-style prefix. Compare case-insensitively on the head only.
        head_len = len(src)
        if len(path) < head_len:
            continue
        if path[:head_len].lower() != src.lower():
            continue
        remainder = path[head_len:]
        # Normalize the seam: ensure exactly one backslash between dst and
        # remainder, regardless of whether remainder starts with \ or /.
        if remainder.startswith(("\\", "/")):
            remainder = remainder[1:]
        return dst + "\\" + remainder
    return path


def translate_all(paths: Iterable[str]) -> list[str]:
    """Convenience for batch rewrites (used by the backfill script)."""
    return [translate(p) or p for p in paths]
