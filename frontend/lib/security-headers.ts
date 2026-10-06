// SEC-P1-5: browser security headers and a cross-origin guard for cookie-authed
// state-changing requests. Applied in proxy.ts on every response it returns.
//
// The CSP is strict where it protects against clickjacking and injection
// (frame-ancestors, object-src, base-uri, form-action) and permissive exactly
// where the app needs it: hls.js spins a worker from a blob and feeds a
// MediaSource (worker-src/media-src blob:), the Cast sender SDK loads from
// www.gstatic.com and opens a gstatic iframe, art and poster images can be
// data: or blob:, and self-hosted fonts plus the vestigial Google Fonts
// preconnect are allowed. 'unsafe-inline' for scripts/styles is kept on
// purpose: Next injects inline hydration scripts and inline styles and this app
// does not use per-request nonces.

export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  // gstatic hosts are listed without a scheme so the Cast SDK's sub-scripts
  // load over whatever scheme the page uses (http on a LAN install, https
  // through the tunnel); on an https page the browser's mixed-content rules
  // still block any http load, so this does not weaken a tunneled deploy.
  "img-src 'self' data: blob: *.gstatic.com",
  "media-src 'self' blob:",
  "script-src 'self' 'unsafe-inline' www.gstatic.com",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' data: https://fonts.gstatic.com",
  "connect-src 'self' www.gstatic.com",
  "worker-src 'self' blob:",
  "frame-src 'self' www.gstatic.com",
  "manifest-src 'self'",
].join("; ");

// HSTS value when the request genuinely arrived over HTTPS. Two years,
// includeSubDomains. No preload (that is a deliberate, separate decision).
export const STRICT_TRANSPORT_SECURITY = "max-age=63072000; includeSubDomains";

// Build the response security headers. HSTS is included only over HTTPS so a
// plain-HTTP LAN install doesn't send a header browsers would honour on the
// next (non-existent) HTTPS visit.
export function securityHeaders(opts: { https: boolean }): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  };
  if (opts.https) headers["Strict-Transport-Security"] = STRICT_TRANSPORT_SECURITY;
  return headers;
}

const STATE_CHANGING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// Whether a request is a cookie-authed, state-changing BFF call whose Origin is
// not this site's own origin. Those are rejected (403) as CSRF defense in depth.
// Bearer-authed calls (the native app) are exempt: they don't ride a cookie and
// routinely send no Origin. A same-origin request (Origin equals ours, or no
// Origin at all, e.g. a top-level form post or a non-browser client) is allowed.
export function isForbiddenCrossOrigin(input: {
  method: string;
  pathname: string;
  origin: string | null | undefined;
  selfOrigin: string;
  hasBearer: boolean;
}): boolean {
  if (!STATE_CHANGING.has(input.method.toUpperCase())) return false;
  if (!input.pathname.startsWith("/api/")) return false;
  if (input.hasBearer) return false;
  if (!input.origin) return false;
  return input.origin !== input.selfOrigin;
}
