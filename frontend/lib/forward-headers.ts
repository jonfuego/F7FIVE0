// Fix A (criterion 18): build the header set for a request the Next proxy
// forwards to a backend, without letting a direct LAN browser spoof its way
// past the backend's trusted-proxy gate (SEC-P1-1, app/services/trusted_proxy).
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
// direct browser by address. Instead the front door (Caddy, written by Setup)
// injects a shared secret header; proxy.ts decides `trusted` from that secret
// and passes it in here. When the request did NOT come through the front door
// (the normal LAN case, or cloudflared / Tailscale which cannot inject the
// secret), the client-IP headers are stripped, so the backend records loopback
// rather than a forged value. The spoof is defeated either way.
//
// x-forwarded-host / x-forwarded-proto are ALWAYS set from the sanitised,
// allowlisted origin that proxy.ts derived through origin.ts, never from the raw
// browser header. This file intentionally does not read any raw forwarded
// header itself; origin.ts is the one place that does.
//
// Build-included file: import origin WITHOUT the .ts extension (a .ts import
// here breaks `next build` with TS5097). Test files import it with .ts.

// The shared secret header the front door (Caddy) injects to mark its traffic
// as coming from a trusted proxy. proxy.ts compares its value against
// TRUSTED_PROXY_SECRET. It must never reach the backend.
export const TRUST_HEADER = "x-f7five0-proxy";

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
  // shared secret). When false, nothing about the client IP is trusted.
  trusted: boolean;
};

// Build the headers for the proxied request. Pure: no env reads, no raw
// forwarded-header reads (the caller already resolved siteOrigin / proto).
export function buildForwardHeaders(reqHeaders: Headers, opts: ForwardOpts): Headers {
  const headers = new Headers(reqHeaders);

  // The trust secret is for the hop into Next only; never forward it on.
  headers.delete(TRUST_HEADER);

  // Only a request from our own front door may carry genuine client-IP
  // headers; otherwise strip them so a direct LAN browser cannot forge one.
  if (!opts.trusted) {
    for (const name of CLIENT_IP_HEADERS) headers.delete(name);
  }

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
