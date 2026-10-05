"""Unit tests for the in-process live hub (item 8b).

These exercise the hub without an event loop or HTTP: the envelope shape, that a
publish with no loop bound is a harmless no-op, and that same-loop delivery
reaches a subscriber's queue.
"""
from __future__ import annotations

import asyncio
import uuid

from app.services import live_hub
from app.services.live_hub import LiveEvent, LiveHub


def test_envelope_shape():
    e = LiveEvent(type="x.y", data={"a": 1})
    env = e.to_envelope()
    assert set(env) == {"type", "data", "ts", "id"}
    assert env["type"] == "x.y"
    assert env["data"] == {"a": 1}
    assert isinstance(env["ts"], float)
    assert isinstance(env["id"], str) and env["id"]


def test_publish_with_no_loop_is_noop():
    # A fresh hub has no loop bound: publishing must not raise even though there
    # are no listeners (the scheduler may fire before anyone connects).
    hub = LiveHub()
    ev = hub.publish_event("library.scan_finished", {"ok": True})
    assert ev.type == "library.scan_finished"
    assert hub.subscriber_count == 0


def test_same_loop_delivery_reaches_subscriber():
    async def _run():
        hub = LiveHub()
        hub.bind_loop(asyncio.get_running_loop())
        sub = hub.subscribe(user_id=uuid.uuid4())
        hub.publish_event("hub.test", {"n": 7})
        event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        assert event.type == "hub.test"
        assert event.data == {"n": 7}
        hub.unsubscribe(sub)
        assert hub.subscriber_count == 0

    asyncio.run(_run())


def test_module_publish_uses_singleton():
    # The module-level publish() targets the shared `hub`. With no loop bound in
    # a unit-test process it is a no-op but still returns the built event.
    ev = live_hub.publish("library.scan_finished", {"ping": True})
    assert ev.type == "library.scan_finished"
    assert ev.data == {"ping": True}
