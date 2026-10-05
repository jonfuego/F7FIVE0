"""In-process live-event hub for the Server-Sent Events (SSE) live channel.

Why SSE and not WebSockets: both pass the Next standalone `proxy.ts`, but the
browser reaches the API through cookie-to-Bearer BFF route handlers, and a Next
route handler cannot accept a WebSocket `Upgrade`. SSE is a plain long HTTP
response, so it works through the BFF and rides the same route HLS streaming
already uses. See `docs/realtime.md` for the spike results.

Single worker only. The API runs one uvicorn worker (CLAUDE.md), so this hub
living in process memory reaches every connected client. If the API is ever
scaled to multiple workers, this hub would only see the subscribers on its own
worker; a cross-worker fan-out (PostgreSQL LISTEN/NOTIFY, or Redis pub/sub)
would be needed then. That is called out here and in `docs/realtime.md` so the
constraint is not silently violated.

The hub is transport-agnostic: it deals in `LiveEvent` envelopes and asyncio
queues. The SSE endpoint in `app/api/live.py` owns the wire format.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("f7five0.live")

# How many events a slow subscriber may fall behind before we drop it. A client
# that cannot keep up (dead TCP connection the OS has not torn down yet) must
# not pin events in memory forever. On overflow the subscriber is dropped and
# its SSE response ends; the client reconnects and the server re-sends state.
_SUBSCRIBER_QUEUE_MAX = 256


@dataclass(slots=True)
class LiveEvent:
    """A typed event envelope pushed to live-channel subscribers.

    type: a dotted event name, e.g. "library.scan_finished" or "hub.ping".
    data: a JSON-serializable payload (may be None).
    ts:   server UNIX time (seconds, float) when the event was created. Clients
          combine this with the /api/time endpoint to reason about the server
          clock.
    id:   a unique event id, usable as the SSE `id:` field for client dedupe.
    """

    type: str
    data: Any = None
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_envelope(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data, "ts": self.ts, "id": self.id}


class _Subscriber:
    """One connected client's event queue."""

    __slots__ = ("queue", "user_id")

    def __init__(self, user_id: Optional[uuid.UUID]) -> None:
        self.queue: asyncio.Queue[LiveEvent] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAX
        )
        self.user_id = user_id


class LiveHub:
    """Fan-out of `LiveEvent`s to every connected subscriber.

    Thread-and-task safe for the one case that matters: `publish` may be called
    from a background-scheduler thread (not the event loop). It binds the loop
    the hub was created on and hands the fan-out to that loop with
    `call_soon_threadsafe`, so publishers never need to be async or hold a lock.
    """

    def __init__(self) -> None:
        self._subscribers: set[_Subscriber] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the event loop so thread publishers can reach it."""
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self, user_id: Optional[uuid.UUID] = None) -> _Subscriber:
        sub = _Subscriber(user_id)
        self._subscribers.add(sub)
        log.debug("live subscriber added (now %d)", len(self._subscribers))
        return sub

    def unsubscribe(self, sub: _Subscriber) -> None:
        self._subscribers.discard(sub)
        log.debug("live subscriber removed (now %d)", len(self._subscribers))

    def _deliver(self, event: LiveEvent) -> None:
        """Push one event to every subscriber. Runs on the event loop."""
        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow/dead client: drop it. Its SSE loop sees the queue stop
                # and ends; the client reconnects and gets fresh state.
                log.warning("dropping slow live subscriber (queue full)")
                self.unsubscribe(sub)

    def publish(self, event: LiveEvent) -> None:
        """Publish an event to all subscribers.

        Safe from any thread. If called on the hub's own event loop the
        delivery is immediate; from another thread it is marshalled onto the
        loop with `call_soon_threadsafe`. When no loop is bound yet (nothing
        has ever connected) the event is simply dropped: nobody is listening.
        """
        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
        else:
            loop.call_soon_threadsafe(self._deliver, event)

    def publish_event(self, type: str, data: Any = None) -> LiveEvent:
        """Convenience: build a `LiveEvent` and publish it. Returns the event
        (handy for tests and for logging the generated id)."""
        event = LiveEvent(type=type, data=data)
        self.publish(event)
        return event


# Process-wide singleton. Other server code publishes through `hub` or the
# module-level `publish` helper; the SSE endpoint subscribes through it.
hub = LiveHub()


def publish(type: str, data: Any = None) -> LiveEvent:
    """Module-level publish API for other server code.

    Example (from a scheduler job):

        from app.services import live_hub
        live_hub.publish("library.scan_finished", {"ok": True})
    """
    return hub.publish_event(type, data)
