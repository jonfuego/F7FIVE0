"""Radarr v3 API client.

Endpoints used:
    GET /api/v3/movie            — full library, includes movieFile if present
    GET /api/v3/movie/{id}       — single movie

The Radarr payload already embeds `movieFile.path`, `movieFile.size`,
`movieFile.mediaInfo.{videoCodec,audioCodec,...}`. We prefer Radarr's own
values when ffprobe hasn't run yet; ffprobe overwrites them later.
"""
from __future__ import annotations

from typing import Any

from app.services.arr._base import _ArrClient


class RadarrClient(_ArrClient):
    service_name = "radarr"
    api_version = "v3"

    def list_movies(self) -> list[dict[str, Any]]:
        return self._get("movie")

    def get_movie(self, radarr_id: int) -> dict[str, Any]:
        return self._get(f"movie/{radarr_id}")

    def movie_lookup(self, term: str) -> list[dict[str, Any]]:
        return self._get("movie/lookup", params={"term": term})

    def add_movie(
        self, tmdb_id: int, quality_profile_id: int, root_folder: str,
        *, search: bool = True,
    ) -> dict[str, Any]:
        """Add a movie to Radarr by TMDB id and trigger a search.

        Radarr's POST /movie wants a full movie resource, so we look the
        movie up first (term=tmdb:<id>), then overlay the quality profile,
        root folder, and monitoring before posting. Raises ArrClientError
        if the lookup returns nothing for the id."""
        results = self.movie_lookup(f"tmdb:{tmdb_id}")
        if not results:
            from app.services.arr._base import ArrClientError
            raise ArrClientError(f"radarr lookup returned nothing for tmdb:{tmdb_id}")
        movie = results[0]
        movie["qualityProfileId"] = quality_profile_id
        movie["rootFolderPath"] = root_folder
        movie["monitored"] = True
        movie["minimumAvailability"] = "released"
        movie["addOptions"] = {"searchForMovie": search}
        return self._post("movie", json=movie)

    def rescan_movie(self, radarr_id: int) -> dict[str, Any]:
        """Queue a RescanMovie command on Radarr."""
        return self._post("command", json={"name": "RescanMovie", "movieIds": [radarr_id]})

    def get_media_management(self) -> dict[str, Any]:
        """GET /api/v3/config/mediamanagement. Returns keys including renameMovies."""
        data = self._get("config/mediamanagement")
        return data if isinstance(data, dict) else {}

    def update_movie_path(self, radarr_id: int, new_folder: str) -> dict[str, Any]:
        """Update a movie's rootFolderPath in Radarr (move files off).

        GETs the current movie resource, updates `rootFolderPath` and
        `moveFiles=false`, then PUTs it back so Radarr knows the new location
        without triggering its own file move.
        """
        movie = self.get_movie(radarr_id)
        movie["rootFolderPath"] = new_folder
        return self._put(f"movie/{radarr_id}", json={**movie, "moveFiles": False})
