/** App client for the live channel (Server-Sent Events + command POST).
 *
 * React Native has no built-in EventSource and its fetch does not stream
 * reliably, so the default transport uses XMLHttpRequest (which RN implements)
 * and parses the SSE byte stream incrementally from xhr.responseText. The whole
 * module is dependency-injected (transport, command sender, timers) so it
 * unit-tests in Node with no native modules, like the api client.
 *
 * Auth: the app holds a Bearer token (ApiClient keeps it in memory). A getter
 * supplies it so the channel always uses the current token, and a 401 ends the
 * stream and triggers a reconnect that fetches a fresh token.
 *
 * Features: parses the typed envelope, is heartbeat-aware (a missed heartbeat
 * forces a reconnect), and reconnects with exponential backoff. The transport
 * rationale (SSE over WebSockets) is in docs/realtime.md.
 */

// The typed event envelope. Mirrors services/live_hub.LiveEvent on the server.
export type LiveEvent<T = unknown> = {
  type: string;
  data: T;
  /** Server UNIX time (seconds) the event was created. */
  ts: number;
  /** Unique event id (usable for dedupe). */
  id: string;
};

export type LiveStatus = "connecting" | "open" | "reconnecting" | "closed";

/** A single SSE connection. Resolves (or rejects) only when the stream ends;
 * calls onFrame for every raw SSE `data:` payload while open. The default
 * implementation is xhrTransport below; tests inject a fake. */
export interface LiveTransport {
  open(args: {
    url: string;
    token: string | null;
    onOpen: () => void;
    onFrame: (data: string) => void;
    onClose: (info: { status: number }) => void;
  }): { close: () => void };
}

export type LiveChannelDeps = {
  /** Fixed base URL, or a getter so the server can change at runtime. */
  baseUrl: string | (() => string);
  /** Returns the current access token (or null when signed out). */
  getToken: () => string | null;
  onEvent?: (event: LiveEvent) => void;
  onStatus?: (status: LiveStatus) => void;
  /** Sends a command POST. Injected so it reuses the app's ApiClient. */
  sendCommand?: (type: string, data: unknown) => Promise<LiveEvent | null>;
  transport?: LiveTransport;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  /** No frame within this window => assume dead and reconnect. Server pings
   * ~every 20s, so 45s is safe. */
  heartbeatTimeoutMs?: number;
  setTimeoutImpl?: typeof setTimeout;
  clearTimeoutImpl?: typeof clearTimeout;
};

const DEFAULTS = {
  baseBackoffMs: 1000,
  maxBackoffMs: 30000,
  heartbeatTimeoutMs: 45000,
};

export class LiveChannel {
  private conn: { close: () => void } | null = null;
  private status: LiveStatus = "closed";
  private attempt = 0;
  private stopped = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly baseUrlSource: string | (() => string);
  private readonly getToken: () => string | null;
  private readonly onEvent?: (event: LiveEvent) => void;
  private readonly onStatus?: (status: LiveStatus) => void;
  private readonly sendCommand?: (type: string, data: unknown) => Promise<LiveEvent | null>;
  private readonly transport: LiveTransport;
  private readonly baseBackoffMs: number;
  private readonly maxBackoffMs: number;
  private readonly heartbeatTimeoutMs: number;
  private readonly setTimeoutImpl: typeof setTimeout;
  private readonly clearTimeoutImpl: typeof clearTimeout;

  constructor(deps: LiveChannelDeps) {
    this.baseUrlSource = deps.baseUrl;
    this.getToken = deps.getToken;
    this.onEvent = deps.onEvent;
    this.onStatus = deps.onStatus;
    this.sendCommand = deps.sendCommand;
    this.transport = deps.transport ?? xhrTransport;
    this.baseBackoffMs = deps.baseBackoffMs ?? DEFAULTS.baseBackoffMs;
    this.maxBackoffMs = deps.maxBackoffMs ?? DEFAULTS.maxBackoffMs;
    this.heartbeatTimeoutMs = deps.heartbeatTimeoutMs ?? DEFAULTS.heartbeatTimeoutMs;
    this.setTimeoutImpl = deps.setTimeoutImpl ?? setTimeout;
    this.clearTimeoutImpl = deps.clearTimeoutImpl ?? clearTimeout;
  }

  private get baseUrl(): string {
    const v = typeof this.baseUrlSource === "function" ? this.baseUrlSource() : this.baseUrlSource;
    return v.replace(/\/+$/, "");
  }

  connect(): void {
    this.stopped = false;
    this.open();
  }

  close(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.conn) {
      this.conn.close();
      this.conn = null;
    }
    this.setStatus("closed");
  }

  getStatus(): LiveStatus {
    return this.status;
  }

  /** Send a command to the server over the POST half of the transport. */
  async send(type: string, data?: unknown): Promise<LiveEvent | null> {
    if (!this.sendCommand) return null;
    return this.sendCommand(type, data ?? null);
  }

  private open(): void {
    this.clearTimers();
    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const conn = this.transport.open({
      url: `${this.baseUrl}/api/live`,
      token: this.getToken(),
      onOpen: () => {
        this.attempt = 0;
        this.setStatus("open");
        this.armHeartbeat();
      },
      onFrame: (data: string) => {
        this.armHeartbeat();
        let parsed: LiveEvent | null = null;
        try {
          parsed = JSON.parse(data) as LiveEvent;
        } catch {
          return;
        }
        if (parsed) this.onEvent?.(parsed);
      },
      onClose: () => {
        this.scheduleReconnect();
      },
    });
    this.conn = conn;
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.clearTimers();
    if (this.conn) {
      this.conn.close();
      this.conn = null;
    }
    const delay = Math.min(this.maxBackoffMs, this.baseBackoffMs * 2 ** this.attempt);
    this.attempt += 1;
    this.setStatus("reconnecting");
    this.reconnectTimer = this.setTimeoutImpl(() => this.open(), delay);
  }

  private armHeartbeat(): void {
    if (this.heartbeatTimer) this.clearTimeoutImpl(this.heartbeatTimer);
    this.heartbeatTimer = this.setTimeoutImpl(() => {
      this.scheduleReconnect();
    }, this.heartbeatTimeoutMs);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      this.clearTimeoutImpl(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer) {
      this.clearTimeoutImpl(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private setStatus(s: LiveStatus): void {
    if (this.status === s) return;
    this.status = s;
    this.onStatus?.(s);
  }
}

/** Parse complete SSE frames out of a growing buffer. Returns the `data:`
 * payloads found and the leftover (incomplete) tail. Exported for tests. */
export function parseSseChunk(buffer: string): { payloads: string[]; rest: string } {
  const payloads: string[] = [];
  // Frames are separated by a blank line.
  let idx: number;
  let rest = buffer;
  // Normalize CRLF so the split works regardless of line endings.
  rest = rest.replace(/\r\n/g, "\n");
  while ((idx = rest.indexOf("\n\n")) !== -1) {
    const frame = rest.slice(0, idx);
    rest = rest.slice(idx + 2);
    const dataLines = frame
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice("data:".length).trimStart());
    if (dataLines.length > 0) payloads.push(dataLines.join("\n"));
  }
  return { payloads, rest };
}

/** Default transport: XMLHttpRequest with incremental responseText parsing.
 * RN implements XMLHttpRequest and fires onprogress as bytes arrive. */
export const xhrTransport: LiveTransport = {
  open({ url, token, onOpen, onFrame, onClose }) {
    const xhr = new XMLHttpRequest();
    let consumed = 0;
    let buffer = "";
    let opened = false;

    xhr.open("GET", url, true);
    xhr.setRequestHeader("Accept", "text/event-stream");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.onreadystatechange = () => {
      if (xhr.readyState === xhr.HEADERS_RECEIVED && !opened) {
        opened = true;
        if (xhr.status >= 200 && xhr.status < 300) onOpen();
      }
    };
    xhr.onprogress = () => {
      const text = xhr.responseText;
      const fresh = text.slice(consumed);
      consumed = text.length;
      buffer += fresh;
      const { payloads, rest } = parseSseChunk(buffer);
      buffer = rest;
      for (const p of payloads) onFrame(p);
    };
    xhr.onerror = () => onClose({ status: xhr.status || 0 });
    xhr.onload = () => onClose({ status: xhr.status || 0 });

    try {
      xhr.send();
    } catch {
      onClose({ status: 0 });
    }

    return {
      close: () => {
        try {
          xhr.abort();
        } catch {
          // ignore
        }
      },
    };
  },
};

/** Fetch the server clock and estimate the offset + round-trip to it.
 *
 * offsetMs is (serverClock - localClock) at the request midpoint; add it to a
 * local Date.now() to estimate the server clock. Used so live positions and
 * watch-together sync reference one authoritative clock. */
export async function fetchServerClock(
  baseUrl: string,
  fetchImpl: typeof fetch = fetch,
): Promise<{ offsetMs: number; rttMs: number }> {
  const t0 = Date.now();
  const res = await fetchImpl(`${baseUrl.replace(/\/+$/, "")}/api/time`);
  const t1 = Date.now();
  const body = (await res.json()) as { unix_ms: number };
  const rttMs = t1 - t0;
  const localMid = t0 + rttMs / 2;
  return { offsetMs: body.unix_ms - localMid, rttMs };
}
