"""API clients for the *arr stack. Radarr, Sonarr, Lidarr.

Each client is a thin wrapper around the service's HTTP API. Clients are
configured from `settings` and hold a long-lived `httpx.Client`.
"""
from app.services.arr.radarr import RadarrClient
from app.services.arr.sonarr import SonarrClient
from app.services.arr.lidarr import LidarrClient

__all__ = ["RadarrClient", "SonarrClient", "LidarrClient"]
