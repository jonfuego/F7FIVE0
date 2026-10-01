"""Shared helpers for *arr HTTP clients."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx


class ArrClientError(RuntimeError):
    """Raised when an *arr API call fails in a way the caller should notice."""


class _ArrClient:
    """Base *arr client. Holds the httpx.Client and the API key."""

    api_version: str = "v3"
    service_name: str = "arr"

    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0) -> None:
        self._log = logging.getLogger(f"f7five0.arr.{self.service_name}")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=f"{self.base_url}/api/{self.api_version}",
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "_ArrClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # -- HTTP plumbing ------------------------------------------------------
    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        if not self.configured:
            raise ArrClientError(f"{self.service_name} not configured (missing api key)")
        try:
            resp = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ArrClientError(f"{self.service_name} GET {path} failed: {exc}") from exc
        if resp.status_code == 401:
            raise ArrClientError(f"{self.service_name} rejected API key (401)")
        if resp.status_code >= 400:
            raise ArrClientError(
                f"{self.service_name} GET {path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    def _post(self, path: str, json: Optional[dict] = None) -> Any:
        if not self.configured:
            raise ArrClientError(f"{self.service_name} not configured (missing api key)")
        try:
            resp = self._client.post(path, json=json or {})
        except httpx.HTTPError as exc:
            raise ArrClientError(f"{self.service_name} POST {path} failed: {exc}") from exc
        if resp.status_code == 401:
            raise ArrClientError(f"{self.service_name} rejected API key (401)")
        if resp.status_code >= 400:
            raise ArrClientError(
                f"{self.service_name} POST {path} returned {resp.status_code}: {resp.text[:200]}"
            )
        # Command endpoints return 201 with a JSON body. Empty bodies fall through
        # to None so callers can branch on the response.
        if not resp.content:
            return None
        return resp.json()

    def ping(self) -> bool:
        """Cheap reachability check. Returns True if the service answers."""
        try:
            self._get("system/status")
            return True
        except ArrClientError:
            return False
