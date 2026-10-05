"""Live channel SSE + server-clock endpoint (item 8b/8d, criterion 20/22).

Covers:
  - auth rejection: GET /api/live with NO bearer token returns 401.
  - a published event is received by a connected SSE client.
  - POST /api/live/command publishes and echoes the envelope.
  - GET /api/time returns a server clock a client can offset against.

The `client` fixture from conftest overrides current_user, so it is used for
the authenticated paths. A second TestClient WITHOUT that override is built
locally to prove the no-token rejection.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.live import _sse_frame, sse_event_stream
from app.db import get_db
from app.main import app
from app.services import live_hub
from app.services.live_hub import LiveHub


@pytest.fixture()
def unauthed(db_session):
    """TestClient wired to the test DB but with NO current_user override, so the
    real Bearer-token dependency runs and rejects an anonymous request."""
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()
        app.dependency_overrides.clear()


def test_live_rejects_without_token(unauthed):
    # No Authorization header at all: the shared get_bearer_token dependency
    # 401s before the stream body runs.
    r = unauthed.get("/api/live")
    assert r.status_code == 401
    assert r.json()["detail"] == "missing_bearer_token"


def test_live_rejects_bad_token(unauthed):
    r = unauthed.get("/api/live", headers={"authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def _data_payloads(frames: list[bytes]) -> list[dict]:
    """Parse the `data:` line out of each SSE frame."""
    out: list[dict] = []
    for frame in frames:
        for line in frame.decode("utf-8").splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[len("data:"):].strip()))
    return out


def test_published_event_is_received_by_connected_client():
    """Drive the real SSE wire generator against the real hub: subscribe,
    publish an event from "server code", and assert the connected subscriber
    receives it in the envelope shape. This exercises `sse_event_stream` (the
    exact generator the /api/live route streams) and the hub fan-out.
    """

    async def _run():
        hub = LiveHub()
        hub.bind_loop(asyncio.get_running_loop())
        sub = hub.subscribe(user_id=uuid.uuid4())
        gen = sse_event_stream(sub, hello_data={"user_id": "u"}, heartbeat_sec=5.0)

        # Opening comment, then the hub.hello event.
        first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert first == b": connected\n\n"
        hello = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert _data_payloads([hello])[0]["type"] == "hub.hello"

        # Now publish a real event the way server code does.
        event = hub.publish_event("library.scan_finished", {"ok": True})
        frame = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        payload = _data_payloads([frame])[0]
        assert payload["type"] == "library.scan_finished"
        assert payload["data"] == {"ok": True}
        assert payload["id"] == event.id
        assert isinstance(payload["ts"], (int, float))

        await gen.aclose()
        hub.unsubscribe(sub)

    asyncio.run(_run())


def test_heartbeat_emitted_on_idle():
    """With no events, the generator emits a hub.ping within the heartbeat
    interval so idle connections stay open."""

    async def _run():
        hub = LiveHub()
        hub.bind_loop(asyncio.get_running_loop())
        sub = hub.subscribe()
        gen = sse_event_stream(sub, heartbeat_sec=0.05)
        await gen.__anext__()  # comment
        await gen.__anext__()  # hello
        ping = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert _data_payloads([ping])[0]["type"] == "hub.ping"
        await gen.aclose()

    asyncio.run(_run())


def test_sse_frame_format():
    event = live_hub.LiveEvent(type="a.b", data={"x": 1})
    frame = _sse_frame(event).encode("utf-8")
    text = frame.decode("utf-8")
    assert text.startswith(f"id: {event.id}\n")
    assert "event: a.b\n" in text
    assert text.endswith("\n\n")


def test_command_publishes_and_echoes(client):
    r = client.post(
        "/api/live/command",
        json={"type": "room.play", "data": {"at": 12.5}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "room.play"
    # The command payload is namespaced with the sender under "payload".
    assert body["data"]["payload"] == {"at": 12.5}
    assert "from_user_id" in body["data"]
    assert isinstance(body["ts"], (int, float))
    assert body["id"]


def test_server_time_endpoint(client):
    before = time.time()
    r = client.get("/api/time")
    after = time.time()
    assert r.status_code == 200, r.text
    body = r.json()
    assert "unix_ms" in body and "unix_sec" in body
    # The reported clock sits within the request window (allowing slop).
    assert before - 1 <= body["unix_sec"] <= after + 1
    assert abs(body["unix_ms"] / 1000.0 - body["unix_sec"]) < 1.0
