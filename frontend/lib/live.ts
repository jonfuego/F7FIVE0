// Web client for the live channel (Server-Sent Events + command POST).
//
// Connects to the BFF route /api/live (which swaps the session cookie for the
// Bearer token and streams the backend's text/event-stream back). Parses the
// typed event envelope, is heartbeat-aware (a missed heartbeat forces a
// reconnect), and reconnects with exponential backoff. Commands go back to the
// server over POST /api/live/command.
//
// Transport rationale (WebSocket vs SSE) is in docs/realtime.md: the
// EventSource goes through the cookie-to-Bearer BFF route, which cannot
// accept a WebSocket Upgrade, and rides the same long-HTTP path HLS uses.

"use client";

// The typed event envelope. Mirrors services/live_hub.LiveEvent on the server.
export type LiveEvent<T = unknown> = {
  type: string;
  data: T;
  // Server UNIX time (seconds) the event was created.
  ts: number;
  // Unique event id (usable for dedupe).
  id: string;
};

export type LiveStatus = "connecting" | "open" | "reconnecting" | "closed";

export type LiveChannelOptions = {
  // Called for every event received (including hub.hello / hub.ping).
  onEvent?: (event: LiveEvent) => void;
  // Called when the connection status changes.
  onStatus?: (status: LiveStatus) => void;
  // Base reconnect delay in ms (doubles each attempt up to maxBackoffMs).
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  // If no frame (event or heartbeat) arrives within this window, assume the
  // link is dead and reconnect. The server pings every ~20s, so 45s is safe.
  heartbeatTimeoutMs?: number;
  // Injectable for tests. Defaults to the global EventSource.
  eventSourceFactory?: (url: string) => EventSourceLike;
  // Injectable for tests. Defaults to the global fetch.
  fetchImpl?: typeof fetch;
};

// The slice of EventSource the channel uses, so tests can supply a fake.
export interface EventSourceLike {
  onopen: ((this: unknown, ev: Event) => void) | null;
  onmessage: ((this: unknown, ev: MessageEvent) => void) | null;
  onerror: ((this: unknown, ev: Event) => void) | null;
  close: () => void;
}

const DEFAULTS = {
  baseBackoffMs: 1000,
  maxBackoffMs: 30000,
  heartbeatTimeoutMs: 45000,
};

export class LiveChannel {
  private es: EventSourceLike | null = null;
  private status: LiveStatus = "closed";
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private readonly opts: Required<
    Omit<LiveChannelOptions, "onEvent" | "onStatus" | "eventSourceFactory" | "fetchImpl">
  > &
    Pick<LiveChannelOptions, "onEvent" | "onStatus">;
  private readonly makeES: (url: string) => EventSourceLike;
  private readonly fetchImpl: typeof fetch;

  constructor(options: LiveChannelOptions = {}) {
    this.opts = {
      baseBackoffMs: options.baseBackoffMs ?? DEFAULTS.baseBackoffMs,
      maxBackoffMs: options.maxBackoffMs ?? DEFAULTS.maxBackoffMs,
      heartbeatTimeoutMs: options.heartbeatTimeoutMs ?? DEFAULTS.heartbeatTimeoutMs,
      onEvent: options.onEvent,
      onStatus: options.onStatus,
    };
    this.makeES =
      options.eventSourceFactory ??
      ((url: string) => new EventSource(url) as unknown as EventSourceLike);
    this.fetchImpl = options.fetchImpl ?? ((...a) => fetch(...a));
  }

  /** Open the channel. Safe to call once; use close() to tear down. */
  connect(): void {
    this.stopped = false;
    this.open();
  }

  /** Permanently close the channel and cancel any pending reconnect. */
  close(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this.setStatus("closed");
  }

  getStatus(): LiveStatus {
    return this.status;
  }

  /** Send a command to the server over the POST half of the transport. */
  async send(type: string, data?: unknown): Promise<LiveEvent | null> {
    try {
      const res = await this.fetchImpl("/api/live/command", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ type, data: data ?? null }),
      });
      if (!res.ok) return null;
      return (await res.json()) as LiveEvent;
    } catch {
      return null;
    }
  }

  private open(): void {
    this.clearTimers();
    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const es = this.makeES("/api/live");
    this.es = es;

    es.onopen = () => {
      this.attempt = 0;
      this.setStatus("open");
      this.armHeartbeat();
    };
    es.onmessage = (ev: MessageEvent) => {
      this.armHeartbeat();
      let parsed: LiveEvent | null = null;
      try {
        parsed = JSON.parse(ev.data as string) as LiveEvent;
      } catch {
        return;
      }
      if (parsed) this.opts.onEvent?.(parsed);
    };
    es.onerror = () => {
      // EventSource would auto-reconnect, but we control backoff ourselves so
      // we can also treat a dead-but-open socket (missed heartbeat) the same
      // way. Close and schedule our own reconnect.
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.clearTimers();
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    const delay = Math.min(
      this.opts.maxBackoffMs,
      this.opts.baseBackoffMs * 2 ** this.attempt,
    );
    this.attempt += 1;
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }

  private armHeartbeat(): void {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      // No frame within the window: the link is dead even if the socket looks
      // open. Force a reconnect.
      this.scheduleReconnect();
    }, this.opts.heartbeatTimeoutMs);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer) {
      clearTimeout(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private setStatus(s: LiveStatus): void {
    if (this.status === s) return;
    this.status = s;
    this.opts.onStatus?.(s);
  }
}

/** Fetch the server clock and estimate the offset + round-trip to it.
 *
 * offsetMs is (serverClock - localClock) at the request midpoint: add it to a
 * local Date.now() to get an estimate of the server's clock. rttMs is the
 * measured round-trip. Used so live positions and watch-together sync reference
 * one authoritative clock. */
export async function fetchServerClock(
  fetchImpl: typeof fetch = fetch,
): Promise<{ offsetMs: number; rttMs: number }> {
  const t0 = Date.now();
  const res = await fetchImpl("/api/time", { cache: "no-store" });
  const t1 = Date.now();
  const body = (await res.json()) as { unix_ms: number };
  const rttMs = t1 - t0;
  const localMid = t0 + rttMs / 2;
  return { offsetMs: body.unix_ms - localMid, rttMs };
}
