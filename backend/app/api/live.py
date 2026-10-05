"""Live channel: a Server-Sent Events (SSE) stream plus a command POST.

Transport choice: SSE over WebSockets. Both pass the Next standalone
`proxy.ts`, but a Next route handler cannot accept a WebSocket Upgrade, so the
browser's cookie-to-Bearer BFF only works for plain HTTP. SSE is a plain
long-lived HTTP response, so it also rides the same route HLS already uses.
Keep `Cache-Control: no-transform` below: without it Next gzips the stream on
the proxy path and holds the frames. The spike results and the VM-passthrough
TO-DO list live in `docs/realtime.md`.

Endpoints:
  GET  /api/live            long-lived `text/event-stream`. Requires a Bearer
                            token (the web BFF swaps the cookie for it; the app
                            sends it directly). Rejects with 401 when absent.
  POST /api/live/command    client -> server command (the SSE direction is
                            server -> client only). Returns the published event
                            envelope so the caller can confirm fan-out.

Envelope (both directions use the same shape, see services/live_hub.LiveEvent):
  {"type": "<dotted.name>", "data": <json|null>, "ts": <server unix sec>,
   "id": "<hex>"}

Heartbeat: the server sends a `hub.ping` event every HEARTBEAT_SEC so idle
connections stay open through proxies and the client can detect a dead link.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import current_user
from app.api.schemas import LiveCommandRequest, LiveEventOut, ServerTimeOut
from app.models.user import User
from app.services import live_hub

log = logging.getLogger("f7five0.api.live")

router = APIRouter()

# Seconds between server heartbeats on an idle connection. Short enough to keep
# intermediaries (Cloudflare, Caddy) from idling the connection out, long
# enough to be negligible traffic.
HEARTBEAT_SEC = 20.0


def _sse_frame(event: live_hub.LiveEvent) -> str:
    """Serialize one LiveEvent as an SSE frame.

    `id:` lets the client dedupe / resume; `event:` carries the type so a
    client may bind named listeners; `data:` is the JSON envelope.
    """
    payload = json.dumps(event.to_envelope(), separators=(",", ":"))
    return f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n"


async def sse_event_stream(
    sub: live_hub._Subscriber,
    *,
    hello_data: dict | None = None,
    heartbeat_sec: float = HEARTBEAT_SEC,
) -> AsyncIterator[bytes]:
    """The SSE wire generator for one subscriber.

    Factored out of the route so it is directly unit-testable with asyncio (the
    TestClient does not stream a text/event-stream response incrementally).
    Yields the opening comment, a `hub.hello` event, then one frame per hub
    event, with a `hub.ping` heartbeat on each idle interval. Starlette cancels
    this generator when the client disconnects; the caller's finally
    unsubscribes.
    """
    yield b": connected\n\n"
    hello = live_hub.LiveEvent(type="hub.hello", data=hello_data)
    yield _sse_frame(hello).encode("utf-8")
    while True:
        try:
            event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat_sec)
        except asyncio.TimeoutError:
            ping = live_hub.LiveEvent(type="hub.ping", data=None)
            yield _sse_frame(ping).encode("utf-8")
            continue
        yield _sse_frame(event).encode("utf-8")


@router.get("/live")
async def live_stream(
    user: Annotated[User, Depends(current_user)],
) -> StreamingResponse:
    """Open the live SSE channel for the authenticated user.

    `current_user` enforces the same auth as the rest of the API: a request
    with no Bearer token is rejected with 401 before this body runs.
    """
    hub = live_hub.hub
    # Bind the running loop once so thread publishers (scheduler) can reach it.
    hub.bind_loop(asyncio.get_running_loop())
    sub = hub.subscribe(user_id=user.id)

    async def _gen() -> AsyncIterator[bytes]:
        try:
            async for chunk in sse_event_stream(
                sub, hello_data={"user_id": str(user.id)}
            ):
                yield chunk
        finally:
            hub.unsubscribe(sub)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            # Defeat buffering proxies so events flush promptly.
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/live/command", response_model=LiveEventOut)
def live_command(
    body: LiveCommandRequest,
    user: Annotated[User, Depends(current_user)],
) -> LiveEventOut:
    """Client -> server command. Publishes it to the hub and echoes the event.

    This is the POST half of the SSE+POST transport: the SSE stream is one-way
    (server -> client), so client actions come back over ordinary POSTs. The
    payload is namespaced with the sender's user id so listeners can attribute
    it. Watch-together room commands will build on this.
    """
    event = live_hub.publish(
        body.type,
        {"from_user_id": str(user.id), "payload": body.data},
    )
    return LiveEventOut(type=event.type, data=event.data, ts=event.ts, id=event.id)


@router.get("/time", response_model=ServerTimeOut)
def server_time() -> ServerTimeOut:
    """Server clock for client offset / round-trip estimation.

    The client records its own time before the request and after the response,
    subtracts to get the round-trip, and compares the midpoint to `unix_ms` to
    estimate the offset between its clock and the server's. Used so live-channel
    positions and watch-together sync reference one authoritative clock.
    """
    now = time.time()
    return ServerTimeOut(unix_ms=int(now * 1000), unix_sec=now)
