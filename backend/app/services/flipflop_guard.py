"""Flip-flop guard: check *arr media management settings for conflicts.

When F7FIVE0 owns a library (ownership="f7five0") but the *arr app also has
rename/retag enabled, both will rename files and fight each other.

check_flipflop(library_kind) -> list[str]: returns warning strings.
Best-effort: returns [] when the app is unreachable or not configured.
Never logs the URL or API key.
"""
from __future__ import annotations

import logging

from app.services import arr_settings
from app.services.library_folders import arr_managed

log = logging.getLogger("f7five0.flipflop_guard")


def check_flipflop(library_kind: str) -> list[str]:
    """Return warning strings when the *arr app for library_kind has settings
    that would conflict with F7FIVE0 renaming or retagging files.

    Returns an empty list when the library is not *arr-managed, when the app
    is not configured, or when the check fails for any reason.
    """
    if not arr_managed(library_kind):
        return []

    app = {
        "movies": "radarr",
        "tv": "sonarr",
        "music": "lidarr",
    }.get(library_kind)
    if app is None:
        return []

    if not arr_settings.configured(app):
        return []

    try:
        base_url = arr_settings.url(app)
        api_key = arr_settings.api_key(app)
        if not base_url or not api_key:
            return []

        if app == "radarr":
            from app.services.arr.radarr import RadarrClient
            client = RadarrClient(base_url, api_key)
        elif app == "sonarr":
            from app.services.arr.sonarr import SonarrClient
            client = SonarrClient(base_url, api_key)
        else:
            from app.services.arr.lidarr import LidarrClient
            client = LidarrClient(base_url, api_key)

        try:
            payload = client.get_media_management()
        except Exception:
            return []

        warnings: list[str] = []
        if app == "radarr" and payload.get("renameMovies"):
            warnings.append("Radarr has Rename Movies enabled")
        elif app == "sonarr" and payload.get("renameEpisodes"):
            warnings.append("Sonarr has Rename Episodes enabled")
        elif app == "lidarr" and payload.get("writeAudioTags", "no") != "no":
            warnings.append("Lidarr has Write Audio Tags enabled")
        return warnings
    except Exception:
        log.warning("flipflop_guard check failed for %s", library_kind)
        return []
