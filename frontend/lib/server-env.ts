// Server-only env access. Never import from client components.
//
// The Next app runs on the same host as the FastAPI apps. In prod the
// Cloudflare Tunnel ingress routes /api and /stream to 8001 and 8002, but
// from inside the Next process we skip the tunnel and talk to the backends
// directly over the loopback. Keep these server-only so the URLs never leak
// into the browser bundle.

export const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8001";
export const STREAM_ORIGIN = process.env.STREAM_ORIGIN ?? "http://127.0.0.1:8002";

// Name the cookies once. Changing these values invalidates every open session.
export const ACCESS_COOKIE = "mh_access";
export const REFRESH_COOKIE = "mh_refresh";
