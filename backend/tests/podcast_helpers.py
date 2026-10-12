"""Shared helpers for the podcast tests.

No test here reaches the network. `install_dns` swaps name resolution for a
table (so the SSRF guard sees the addresses the test wants) and
`install_transport` puts an `httpx.MockTransport` behind every guarded fetch.
"""
from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import httpx

from fastapi.testclient import TestClient

from app.models.user import User
from app.services import net_guard
from tests.conftest import make_active_session

FIXTURES = Path(__file__).parent / "fixtures" / "podcasts"
PUBLIC_IP = "93.184.216.34"

# Names the tests use that must resolve to a private address.
PRIVATE_HOSTS = {
    "internal.example": "10.0.0.5",
    "loopback.example": "127.0.0.1",
    "metadata.example": "169.254.169.254",
    "v6loop.example": "::1",
}


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def install_dns(monkeypatch, extra: Optional[dict] = None) -> None:
    """Every host resolves to a public address, except PRIVATE_HOSTS and
    `extra`. An IP literal resolves to itself."""
    table = {**PRIVATE_HOSTS, **(extra or {})}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = table.get(host)
        if ip is None:
            try:
                socket.inet_pton(socket.AF_INET, host)
                ip = host
            except OSError:
                try:
                    socket.inet_pton(socket.AF_INET6, host)
                    ip = host
                except OSError:
                    ip = PUBLIC_IP
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", fake_getaddrinfo)


class Calls:
    """What a mock transport saw."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    def __len__(self) -> int:
        return len(self.requests)


def install_transport(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> Calls:
    calls = Calls()

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.requests.append(request)
        return handler(request)

    monkeypatch.setattr(net_guard, "_transport_override", httpx.MockTransport(wrapped))
    return calls


def make_user(db, *, role: str = "member", name: Optional[str] = None) -> User:
    user = User(
        username=name or f"u-{uuid.uuid4().hex[:8]}", display_name="U",
        password_hash="x", role=role, is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def make_podcast(db, *, title: str = "Show", feed_url: Optional[str] = "https://show.example/feed.xml",
                 source: str = "feed", folder_path: Optional[str] = None) -> "Podcast":
    from app.models.podcast import Podcast
    pod = Podcast(title=title, feed_url=feed_url, source=source, folder_path=folder_path)
    db.add(pod)
    db.flush()
    return pod


def make_episode(db, pod: "Podcast", *, guid: Optional[str] = None, title: str = "Ep",
                 published: Optional[datetime] = None, duration: Optional[int] = 3600,
                 enclosure_url: Optional[str] = "https://cdn.show.example/ep.mp3") -> "PodcastEpisode":
    from app.models.podcast import PodcastEpisode
    ep = PodcastEpisode(
        podcast_id=pod.id, guid=guid or uuid.uuid4().hex, title=title,
        published_at=published or datetime(2025, 3, 1, tzinfo=timezone.utc),
        duration_sec=duration, enclosure_url=enclosure_url, enclosure_type="audio/mpeg",
    )
    db.add(ep)
    db.flush()
    return ep


def subscribe(db, user: User, pod: "Podcast", *, auto_download: bool = False,
              created_at: Optional[datetime] = None) -> "PodcastSubscription":
    from app.models.podcast import PodcastSubscription
    sub = PodcastSubscription(user_id=user.id, podcast_id=pod.id, auto_download=auto_download)
    if created_at is not None:
        sub.created_at = created_at
    db.add(sub)
    db.flush()
    return sub


class Api:
    """One TestClient, acting as whichever user a test names (or nobody)."""

    def __init__(self, db) -> None:
        from app.api.deps import current_session_id, current_user, get_db
        from app.main import app

        self.db, self.app = db, app
        self._current_user, self._current_session_id, self._get_db = current_user, current_session_id, get_db
        app.dependency_overrides[get_db] = self._db
        self.client = TestClient(app)

    def _db(self):
        yield self.db

    def as_user(self, user) -> TestClient:
        _, sess = make_active_session(self.db, user=user)
        self.app.dependency_overrides[self._current_user] = lambda: user
        self.app.dependency_overrides[self._current_session_id] = lambda: sess.id
        return self.client

    def anonymous(self) -> TestClient:
        self.app.dependency_overrides.pop(self._current_user, None)
        self.app.dependency_overrides.pop(self._current_session_id, None)
        return self.client

    def close(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
