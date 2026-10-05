# Realtime transport (live channel groundwork)

Groundwork for watch-together and other push features (scan progress, remote
access status, queue sync). This records the transport spike, the choice, the
local test, and what still needs checking on the VM.

## Transport chosen: Server-Sent Events (SSE) + POST

The live channel is a long-lived `text/event-stream` HTTP response from the API
(`GET /api/live`), with client-to-server commands sent as ordinary
`POST /api/live/command`. WebSockets also work through the proxy (see the local
test below); SSE was kept for the auth model, not because WebSockets fail.

### Why SSE and not WebSockets

The web client reaches the API through the single-origin proxy in
`frontend/proxy.ts` (Next.js 16 "proxy", formerly middleware, Node runtime).
The local test showed that its `NextResponse.rewrite` DOES carry a WebSocket
`Upgrade` through to the API on the standalone server. Transport passthrough is
not the deciding factor. These are:

- Auth. The browser keeps its tokens in httpOnly cookies and reaches the API
  through BFF route handlers that swap the cookie for a Bearer token. A Next
  route handler cannot accept an `Upgrade`, so a browser WebSocket would have
  to skip the BFF and go through `proxy.ts` straight to the API, and the API
  would then have to accept the session cookie itself. SSE keeps the existing
  model: the browser's `EventSource` goes through the BFF route
  (`frontend/app/api/live/route.ts`), and the native app sends its own Bearer
  and is routed straight to the API by `backendFor()` in `proxy.ts`.
- Front doors. SSE is a plain long HTTP response, the same kind of traffic HLS
  already sends through Cloudflare Tunnel, Tailscale Funnel and Caddy.
  WebSocket passthrough is per-front-door behavior that still needs checking
  on each one.
- What the channel needs today is mostly server-to-client push; client
  commands are rare and fit ordinary POSTs.

Decision (Jon, 2026-10-04): keep SSE + POST.

### Keep `Cache-Control: no-transform` on the stream

Next's built-in response compression gzips a proxied `text/event-stream` when
the client sends `Accept-Encoding: gzip` (Android's HTTP stack does by
default) and then holds the frames until the stream ends. The test below
reproduced this on the rewrite path. `no-transform` in the response's
`Cache-Control` turns that off. `backend/app/api/live.py` and the BFF route
both send it; do not remove it.

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

### WebSocket passthrough spike (2026-10-04)

Built a minimal Next app with the same pins (next 16.3.8, react 19.3.0) and
byte-identical copies of `frontend/proxy.ts`, `frontend/next.config.mjs`
(`output: "standalone"`), `frontend/lib/server-env.ts` and
`frontend/app/api/live/route.ts`; built it with `next build --webpack` and ran
the standalone `node server.js` on :3001. A stand-in API on :8001 answered
WebSocket echo on any path and SSE on `/api/live` (three frames, one second
apart, same headers as `live.py`). Run on Node 22 in a Linux shell on the dev
PC. Full output and the harness: `_personal-removed\batch1\f7five0_realtime-spike_v1.txt`
(gitignored).

| Test | Result |
|------|--------|
| WS direct to :8001 (control) | pass, echo returned |
| WS via :3001 `/api/ws-test` (non-BFF, rewritten to the API) | pass, echo returned |
| WS via :3001 `/api/live` with Bearer (rewritten to the API) | pass, echo returned |
| SSE direct to :8001 | frames at 1 s, 2 s, 3 s |
| SSE via :3001 rewrite, Bearer, `Accept-Encoding: gzip` | frames at 1 s, 2 s, 3 s |
| SSE via :3001 BFF route, cookie | frames at 1 s, 2 s, 3 s |
| Control: SSE rewrite WITHOUT `no-transform`, gzip accepted | gzipped, frames held until the stream ended (3 s) |

### Backend and client tests (pytest / jest)

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

Starlette's `TestClient` buffers a `text/event-stream` response, so the SSE
delivery test drives the extracted `sse_event_stream` generator directly with
asyncio against the real hub. The HTTP-level auth and time tests use the
TestClient normally.

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

If any front door cannot pass SSE cleanly after config, re-evaluate. WebSocket
is a real option (it passes `proxy.ts`), at the cost of cookie auth on the API
for browsers; long-poll is the other fallback.
