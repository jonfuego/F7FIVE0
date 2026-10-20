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

    def rescan_artist(self, lidarr_id: int) -> dict[str, Any]:
        """Queue a RescanArtist command on Lidarr."""
        return self._post("command", json={"name": "RescanArtist", "artistId": lidarr_id})

    def get_media_management(self) -> dict[str, Any]:
        """GET /api/v1/config/mediamanagement. Returns keys including writeAudioTags."""
        data = self._get("config/mediamanagement")
        return data if isinstance(data, dict) else {}

    def update_artist_path(self, lidarr_id: int, new_folder: str) -> dict[str, Any]:
        """Update an artist's path in Lidarr (move files off).

        GETs the current artist resource, updates `path`, then PUTs it back
        so Lidarr knows the new location without triggering its own file move.
        """
        artist = self.get_artist(lidarr_id)
        artist["path"] = new_folder
        return self._put(f"artist/{lidarr_id}", json={**artist, "moveFiles": False})
