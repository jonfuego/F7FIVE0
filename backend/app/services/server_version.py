"""The F7FIVE0 version that is installed on this PC.

Setup records it in <install>/version.json as {"version", "installed_at"}
(installer/install.ps1). Nothing else is a source of truth: the API, the
Admin > Updates page, and the updater's health check all read it from here.
A server that was not put in place by Setup (a git checkout, a dev stack) has
no record and reports 0.0.0-dev.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import _REPO_ROOT, settings

FALLBACK = "0.0.0-dev"

# Semantic version: no leading zeros in the numbers, optional -prerelease and
# +build. Setup's own versions are X.Y.Z or X.Y.Z-label (a test build).
VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


def version_file() -> Path:
    raw = settings.server_version_file.strip()
    return Path(raw) if raw else _REPO_ROOT / "version.json"


def installed() -> str:
    """The installed version, or 0.0.0-dev when there is no usable record.
    PowerShell 5.1 writes a BOM, hence utf-8-sig."""
    try:
        data = json.loads(version_file().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return FALLBACK
    value = data.get("version") if isinstance(data, dict) else None
    if isinstance(value, str) and VERSION_RE.match(value.strip()):
        return value.strip()
    return FALLBACK
