// Build the header set for a request the Next proxy forwards to a backend,
// without letting a direct LAN browser spoof its way past the backend's
// trusted-proxy gate (SEC-P1-1, app/services/trusted_proxy).
//
// The backend trusts loopback for forwarded headers and Next IS the loopback
// peer, so whatever Next forwards is attributed to a trusted front door. The
// old proxy copied EVERY inbound header and set x-forwarded-host/proto from the
// raw browser values, so a browser on http://<lan-ip>:3101 could send
// CF-Connecting-IP / X-Forwarded-For (forge an audit IP or slip the login
// throttle) or X-Forwarded-Host (poison a signed URL host).
//
// Next 16's proxy runs on a web NextRequest and cannot read the client socket
// peer IP (no request.ip, no socket), so it cannot tell a real proxy from a
// direct browser by address on its own. Two signals feed trust here:
//
//   1. Fix A: a front door (Caddy, written by Setup) injects a shared secret
//      header; proxy.ts compares it against TRUSTED_PROXY_SECRET and passes the
//      result as opts.trusted. A trusted hop keeps its genuine client-IP
//      headers.
//
//   2. Fix B: the launcher (server-wrapper.js) stamps the real socket peer as
//      x-f7five0-peer (OVERWRITING any client value) before Next runs, and sets
//      process.env.F7FIVE0_LAUNCHER (which a client can never forge). proxy.ts
//      passes the raw peer header as opts.peer and that flag as
//      opts.launcherActive. When the launcher is active and a peer is present:
//        - a LOOPBACK peer is a LOCAL front door (cloudflared / Caddy /
//          Tailscale terminating on this host over loopback), so its
//          CF-Connecting-IP / X-Forwarded-For pass through, and
//        - a LAN-browser peer has its forgeable client-IP headers stripped and
//          x-forwarded-for set to the real peer IP.
//      With no launcher signal (or no peer), the client-IP headers are stripped
//      and the backend records loopback. Fail closed: we never honour a
//      client-sent peer header.
//
// x-forwarded-host / x-forwarded-proto are ALWAYS set from the sanitised,
// allowlisted origin that proxy.ts derived through origin.ts, never from the raw
// browser header. This file intentionally does not read any raw forwarded
// header itself (not even the peer: the caller passes its value in); origin.ts
// is the one place that reads host/proto.
//
// Build-included file: import origin WITHOUT the .ts extension (a .ts import
// here breaks `next build` with TS5097). Test files import it with .ts.

// The shared secret header the front door (Caddy) injects to mark its traffic
// as coming from a trusted proxy. proxy.ts compares its value against
// TRUSTED_PROXY_SECRET. It must never reach the backend.
export const TRUST_HEADER = "x-f7five0-proxy";

// The header the launcher (server-wrapper.js) stamps with the real socket peer
// IP, overwriting any client value. The launcher is the ONLY writer the proxy
// trusts, and only when F7FIVE0_LAUNCHER is set. It must never reach the backend.
export const PEER_HEADER = "x-f7five0-peer";

// Client-IP headers the backend honours only from a trusted peer. Stripped on
// an untrusted hop so a direct browser cannot forge them.
const CLIENT_IP_HEADERS = [
  "cf-connecting-ip",
  "x-forwarded-for",
  "x-real-ip",
  "forwarded",
] as const;

export type ForwardOpts = {
  // The allowlisted site origin proxy.ts built via siteOriginFromHeaders().
  siteOrigin: string;
  // The scheme proxy.ts resolved via requestProto().
  proto: "http" | "https";
  // Whether this request arrived through our own front door (carried the
  // shared secret). When false, nothing about the client IP is trusted on that
  // basis, but the launcher peer may still apply.
  trusted: boolean;
  // The raw x-f7five0-peer header value the launcher stamped (the real socket
  // peer). null when the header is absent.
  peer?: string | null;
  // Whether the process is running under the launcher (F7FIVE0_LAUNCHER === "1").
  // Only then is the peer trusted; otherwise it may be a client forgery.
  launcherActive?: boolean;
};

// Strip "::ffff:" from an IPv4-mapped IPv6 address so 127.x and LAN checks and
// the forwarded value use the bare IPv4 literal.
function unwrapPeer(peer: string): string {
  const p = peer.trim();
  const m = /^::ffff:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$/i.exec(p);
  return m ? m[1] : p;
}

// Whether a peer address is loopback (a local front door terminating on this
// host). Covers 127.0.0.0/8, ::1, and IPv4-mapped loopback (already unwrapped).
function isLoopbackPeer(peer: string): boolean {
  if (peer === "::1") return true;
  const m = /^(\d{1,3})\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.exec(peer);
  return !!m && Number(m[1]) === 127;
}

// Build the headers for the proxied request. Pure: no env reads, no raw
// forwarded-header reads (the caller already resolved siteOrigin / proto / peer).
export function buildForwardHeaders(reqHeaders: Headers, opts: ForwardOpts): Headers {
  const headers = new Headers(reqHeaders);

  if (opts.trusted) {
    // Fix A: a front-door hop (the shared secret matched). Its CF-Connecting-IP
    // / X-Forwarded-For are the genuine remote IP; keep them.
  } else if (opts.launcherActive && opts.peer && opts.peer.trim()) {
    // Fix B: the launcher stamped a real socket peer.
    const peer = unwrapPeer(opts.peer);
    if (isLoopbackPeer(peer)) {
      // A LOCAL front door (cloudflared / Caddy / Tailscale over loopback).
      // Any local process can set these; that is the same trust the backend
      // already gives a loopback peer. Keep them.
    } else {
      // A LAN browser. Drop its forgeable client-IP headers and record the real
      // peer as x-forwarded-for.
      for (const name of CLIENT_IP_HEADERS) headers.delete(name);
      headers.set("x-forwarded-for", peer);
    }
  } else {
    // No launcher signal, or no peer: fail closed. Strip all client-IP headers
    // so the backend records loopback rather than a forged value.
    for (const name of CLIENT_IP_HEADERS) headers.delete(name);
  }

  // The trust secret and the peer header are for the hop into Next only; never
  // forward them on, whatever the trust decision above.
  headers.delete(TRUST_HEADER);
  headers.delete(PEER_HEADER);

  // The forwarded host/proto the backend uses for signed URLs come from the
  // allowlisted origin, never the raw browser header, trusted or not.
  const host = hostOf(opts.siteOrigin);
  if (host) headers.set("x-forwarded-host", host);
  headers.set("x-forwarded-proto", opts.proto);

  return headers;
}

function hostOf(origin: string): string | null {
  try {
    return new URL(origin).host;
  } catch {
    return null;
  }
}
