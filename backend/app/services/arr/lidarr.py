"""Lidarr v1 API client.

Endpoints used:
    GET /api/v1/artist                         — all artists
    GET /api/v1/artist/{id}                    — single artist
    GET /api/v1/album?artistId={id}            — albums for an artist
    GET /api/v1/track?albumId={id}             — tracks on an album
    GET /api/v1/trackfile?artistId={id}        — track files (paths) for an artist
"""
from __future__ import annotations

from typing import Any

from app.services.arr._base import _ArrClient


class LidarrClient(_ArrClient):
    service_name = "lidarr"
    api_version = "v1"

    def list_artists(self) -> list[dict[str, Any]]:
        return self._get("artist")

    def get_artist(self, lidarr_id: int) -> dict[str, Any]:
        return self._get(f"artist/{lidarr_id}")

    def list_albums(self, artist_id: int) -> list[dict[str, Any]]:
        return self._get("album", params={"artistId": artist_id})

    def list_tracks(self, album_id: int) -> list[dict[str, Any]]:
        return self._get("track", params={"albumId": album_id})

    def list_track_files(self, artist_id: int) -> list[dict[str, Any]]:
        return self._get("trackfile", params={"artistId": artist_id})

    def artist_lookup(self, term: str) -> list[dict[str, Any]]:
        return self._get("artist/lookup", params={"term": term})

    def album_lookup(self, term: str) -> list[dict[str, Any]]:
        """Search MusicBrainz release-groups via Lidarr's lookup proxy.

        Each candidate carries `foreignAlbumId` (the MB release-group MBID)
        which is what the Fix Match apply step writes onto Album.mbid or
        MusicVideoRelease.mbid.
        """
        return self._get("album/lookup", params={"term": term})
