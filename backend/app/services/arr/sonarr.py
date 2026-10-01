"""Sonarr v3 API client.

Endpoints used:
    GET  /api/v3/series                       all series, includes statistics
    GET  /api/v3/series/{id}                  single series
    GET  /api/v3/episode?seriesId={id}        episodes for a series
    GET  /api/v3/episodefile?seriesId={id}    episode files (paths) for a series
    GET  /api/v3/manualimport?folder=...      parsed candidates under a folder
    POST /api/v3/command                      queue a named command (RescanSeries, ManualImport)
    GET  /api/v3/command/{id}                 poll command status
"""
from __future__ import annotations

from typing import Any

from app.services.arr._base import _ArrClient


class SonarrClient(_ArrClient):
    service_name = "sonarr"
    api_version = "v3"

    def list_series(self) -> list[dict[str, Any]]:
        return self._get("series")

    def get_series(self, sonarr_id: int) -> dict[str, Any]:
        return self._get(f"series/{sonarr_id}")

    def series_lookup(self, term: str) -> list[dict[str, Any]]:
        return self._get("series/lookup", params={"term": term})

    def add_series(
        self, tvdb_id: int, quality_profile_id: int, root_folder: str,
        *, search: bool = True,
    ) -> dict[str, Any]:
        """Add a series to Sonarr by TVDB id and search for missing episodes.

        Like Radarr's add, Sonarr's POST /series wants a full resource, so
        we look it up first (term=tvdb:<id>) and overlay the profile, root
        folder, and monitoring. Raises ArrClientError if the lookup returns
        nothing for the id."""
        results = self.series_lookup(f"tvdb:{tvdb_id}")
        if not results:
            from app.services.arr._base import ArrClientError
            raise ArrClientError(f"sonarr lookup returned nothing for tvdb:{tvdb_id}")
        series = results[0]
        series["qualityProfileId"] = quality_profile_id
        series["rootFolderPath"] = root_folder
        series["monitored"] = True
        series["addOptions"] = {
            "searchForMissingEpisodes": search,
            "monitor": "all",
        }
        return self._post("series", json=series)

    def list_episodes(self, series_id: int) -> list[dict[str, Any]]:
        return self._get("episode", params={"seriesId": series_id})

    def list_episode_files(self, series_id: int) -> list[dict[str, Any]]:
        return self._get("episodefile", params={"seriesId": series_id})

    def rescan_series(self, series_id: int) -> dict[str, Any]:
        """Queue a RescanSeries command on Sonarr. This reconciles Sonarr's
        existing EpisodeFile rows with what's on disk (flips hasFile=False
        for files that vanished, updates sizes). It does NOT import new
        files that appeared in the folder; for that, follow up with
        manual_import_candidates + manual_import_command."""
        return self._post("command", json={"name": "RescanSeries", "seriesId": series_id})

    def get_command(self, command_id: int) -> dict[str, Any]:
        """Read the current state of a queued command. `status` transitions
        queued -> started -> completed|failed|aborted."""
        return self._get(f"command/{command_id}")

    def manual_import_candidates(
        self, folder: str, series_id: int, filter_existing_files: bool = True,
    ) -> list[dict[str, Any]]:
        """List candidate files for manual import under a folder.

        Sonarr walks the folder, parses each video filename, and returns a
        list of dicts carrying (path, seriesId, episodes, quality, languages,
        releaseGroup, rejections, ...). Files that already map to a known
        EpisodeFile are filtered out when filter_existing_files=True, which
        is the knob that keeps us from re-importing files we already track."""
        params = {
            "folder": folder,
            "seriesId": series_id,
            "filterExistingFiles": "true" if filter_existing_files else "false",
        }
        return self._get("manualimport", params=params)

    def manual_import_command(
        self, files: list[dict[str, Any]], import_mode: str = "Auto",
    ) -> dict[str, Any]:
        """Queue a ManualImport command with a pre-parsed file list. Each
        file dict must carry at least path + seriesId + episodeIds + quality
        + languages; the shape matches what manual_import_candidates returns
        (trimmed down). importMode: Auto | Move | Copy."""
        return self._post(
            "command",
            json={"name": "ManualImport", "files": files, "importMode": import_mode},
        )
