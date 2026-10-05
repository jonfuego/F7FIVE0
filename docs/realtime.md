# Realtime transport (live channel groundwork)

Groundwork for watch-together and other push features (scan progress, remote
access status, queue sync). This records the transport spike, the choice, the
local test, and what still needs checking on the VM.

## Transport chosen: Server-Sent Events (SSE) + POST

The live channel is a long-lived `text/event-stream` HTTP response from the API
(`GET /api/live`), with client-to-server commands sent as ordinary
`POST /api/live/command`. WebSockets were considered and rejected for this app.

### Why not WebSockets

The web client reaches the API through the single-origin proxy in
`frontend/proxy.ts` (Next.js 16 "proxy", formerly middleware, Node runtime).
That proxy forwards backend-bound requests with `NextResponse.rewrite(target)`:

```ts
// frontend/proxy.ts
return NextResponse.rewrite(target, { request: { headers } });
```

`NextResponse.rewrite` performs an internal, fetch-style rewrite of an ordinary
HTTP request/response. It does not perform an HTTP `Upgrade` handshake and does
not hand the raw socket to the backend, so a WebSocket `Upgrade: websocket`
request cannot complete through it. A browser `new WebSocket("/stream-or-api")`
would have to bypass `proxy.ts` entirely, which breaks the single-origin model
(one port / one tunnel hostname) the whole deployment relies on.

SSE, by contrast, is a plain long HTTP response. It rides the exact same path
that HLS streaming already uses (a long `StreamingResponse` from the backend,
proxied straight through). Because the browser `EventSource` cannot set an
`Authorization` header, the web client connects through a Next BFF route
(`frontend/app/api/live/route.ts`) that swaps the httpOnly session cookie for
the Bearer token and streams the backend body back unchanged. The native app
sets its own `Bearer` header and is routed straight to the API by
`backendFor()` in `proxy.ts`.

Given this is a self-hosted product reached through tunnels (Cloudflare,
Tailscale Funnel) and reverse proxies (Caddy), SSE is also the safer default:
long HTTP responses pass every one of those front doors that HLS already works
through, whereas WebSocket passthrough is per-front-door configuration that can
silently fail. SSE + POST is the choice.

### Shape of what was built

- Backend: `backend/app/api/live.py` - `GET /api/live` (SSE), `POST
  /api/live/command`, `GET /api/time` (server clock). In-process hub in
  `backend/app/services/live_hub.py` with a typed `LiveEvent` envelope
  (`type`, `data`, `ts`, `id`) and a `publish()` API other server code calls.
- The library folder scan publishes a real `library.scan_finished` event
  (`backend/app/scheduler.py`) to prove the hub end to end.
- Web client: `frontend/lib/live.ts` (EventSource + reconnect backoff +
  heartbeat watchdog; `fetchServerClock`). BFF: `frontend/app/api/live/`.
- App client: `mobile/src/live/liveChannel.ts` (XMLHttpRequest SSE transport,
  incremental frame parsing, reconnect backoff, heartbeat watchdog).

### In-process hub, single worker

The hub lives in the API process memory. The API runs ONE uvicorn worker (see
`CLAUDE.md`: "The stream gateway runs one uvicorn worker"; the API is likewise
single-worker so its in-process registries - scheduler, and now this hub - are
authoritative). A publish reaches every connected subscriber on that worker.

If the API is ever scaled to multiple workers, each worker's hub would only see
its own subscribers, so a publish on worker A would not reach a client on
worker B. Crossing that boundary would need an out-of-process fan-out:
PostgreSQL `LISTEN`/`NOTIFY` (already have Postgres) or Redis pub/sub. Do not
add workers without adding that first.

## Local test performed

A full standalone-server WebSocket passthrough test was NOT run in this
environment (no built standalone server + live tunnel here). The choice is made
from the `proxy.ts` code analysis above (rewrite cannot carry an Upgrade) plus
the following local tests that DID run and pass:

1. Backend SSE generator and hub, end to end in-process
   (`backend/tests/api/test_live_channel.py`,
   `backend/tests/services/test_live_hub.py`): subscribe to the exact generator
   the `/api/live` route streams, publish a `library.scan_finished` event from
   "server code", and assert the subscriber receives it in the envelope shape;
   assert the heartbeat frame is emitted on idle; assert the SSE frame format
   (`id:` / `event:` / `data:`). Result: pass.
2. Auth rejection: `GET /api/live` with no Bearer token returns 401
   (`test_live_rejects_without_token`). Result: pass.
3. Server clock: `GET /api/time` returns a clock within the request window
   (`test_server_time_endpoint`). Result: pass.
4. App client SSE parsing and reconnect/heartbeat logic, with an injected
   transport (`mobile/src/live/__tests__/liveChannel.test.ts`). Result: pass.

Note on the TestClient: Starlette's `TestClient` does not stream a
`text/event-stream` response incrementally (it buffers), so the SSE delivery
test drives the extracted `sse_event_stream` generator directly with asyncio
against the real hub. The HTTP-level auth and time tests use the TestClient
normally.

## TO-DO: VM checks (not doable from the dev PC)

Run these on the VM, where the real front doors are configured. For each,
confirm a `GET /api/live` SSE stream stays open, flushes `hub.ping` heartbeats
(~every 20s), and delivers a published event (trigger a library scan and watch
for `library.scan_finished`), and that `POST /api/live/command` returns 200.

- [ ] **Cloudflare Tunnel**: confirm the named tunnel (`F7FIVE0-Tunnel`) passes
      the SSE stream without buffering or idle-timing it out. Cloudflare buffers
      some responses; verify `text/event-stream` with `X-Accel-Buffering: no`
      flushes frames promptly and the 100s idle limit does not close the stream
      (the 20s heartbeat should keep it alive). Check both the named-tunnel and
      dashboard-token paths.
- [ ] **Tailscale Funnel**: confirm Funnel forwards the long SSE response and
      does not buffer or time out the idle connection. Funnel terminates HTTPS;
      verify the heartbeat keeps it open and frames arrive as sent.
- [ ] **Caddy** (`F7FIVE0-Proxy`): confirm the reverse-proxy config streams
      `text/event-stream` with buffering disabled (`flush_interval -1` for the
      live path if needed) so SSE frames are not held back, and that the idle
      heartbeat keeps the connection open.

If any front door cannot pass SSE cleanly after config, re-evaluate: the next
fallback is long-poll, not WebSockets (WebSockets have the same per-front-door
risk plus the `proxy.ts` Upgrade problem above).
