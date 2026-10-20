"""Token-based naming template renderer for the library organizer.

Tokens: {Title}, {Sort Title}, {Year}, {Album Artist}, {Album}, {Artist},
{Track:00}, {Disc}, {Disc:0}, {Season:00}, {Episode:00}, {Series}.

Format suffixes:
  :00  -- zero-pad to 2 digits
  :0   -- bare integer (no padding)

Unknown tokens are left as-is in the output. safe_path / render_safe strip
Windows-illegal characters from each path segment.
"""
from __future__ import annotations

import os
import re

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_UNDERSCORE = re.compile(r'_+')
_TOKEN_RE = re.compile(r'\{([^}]+)\}')


def safe_segment(s: str) -> str:
    """Strip Windows-illegal characters from a single path segment."""
    out = _UNSAFE.sub('_', s)
    out = _MULTI_UNDERSCORE.sub('_', out)
    out = out.strip()
    out = out.strip('.')
    out = out.rstrip(' ')
    return out or '_'


def _apply_format(value: str, fmt: str) -> str:
    if fmt == '00':
        try:
            return str(int(value)).zfill(2)
        except (ValueError, TypeError):
            return value
    if fmt == '0':
        try:
            return str(int(value))
        except (ValueError, TypeError):
            return value
    return value


def render(template: str, tokens: dict) -> str:
    """Replace {Token} and {Token:fmt} placeholders with values from tokens.

    Token lookup is case-sensitive (matches the token names in the spec).
    Unrecognised tokens are left unchanged."""
    def replace(m: re.Match) -> str:
        inner = m.group(1)
        if ':' in inner:
            name, fmt = inner.split(':', 1)
        else:
            name, fmt = inner, ''

        if name not in tokens:
            return m.group(0)

        value = tokens[name]
        if value is None:
            value = ''
        value = str(value)

        if fmt:
            return _apply_format(value, fmt)
        return value

    return _TOKEN_RE.sub(replace, template)


def render_safe(template: str, tokens: dict) -> str:
    """Render the template, then apply safe_segment to each path component."""
    rendered = render(template, tokens)
    parts = re.split(r'[/\\]', rendered)
    return os.sep.join(safe_segment(p) for p in parts)


# ---------------------------------------------------------------------------
# Preset dicts (keyed by kind: "music", "movie", "tv")
# ---------------------------------------------------------------------------
PRESET_PLEX: dict[str, str] = {
    "music": "{Album Artist}/{Album} ({Year})/{Disc:0}{Track:00} - {Title}",
    "movie": "{Title} ({Year})/{Title} ({Year})",
    "tv": "{Series}/Season {Season:00}/{Series} - S{Season:00}E{Episode:00} - {Title}",
}

PRESET_ARR: dict[str, str] = {
    "music": "{Album Artist}/{Album} ({Year})/{Track:00} - {Title}",
    "movie": "{Title} ({Year})/{Title} ({Year})",
    "tv": "{Series}/Season {Season:00}/{Series} - S{Season:00}E{Episode:00} - {Title}",
}

PRESET_FLAT: dict[str, str] = {
    "music": "{Album Artist} - {Album} - {Track:00} - {Title}",
    "movie": "{Title} ({Year})",
    "tv": "{Series} - S{Season:00}E{Episode:00} - {Title}",
}
