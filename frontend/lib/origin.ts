// SEC-P1-1: build the site's own origin for redirects and cookie decisions
// without trusting a raw Host / X-Forwarded-Proto the browser could forge.
//
// The web server is single-origin behind the Next proxy, a reverse proxy, or
// one Cloudflare Tunnel rule. The redirect target (/login) and the cookie
// Secure flag are derived from request headers, which on a plain-LAN install
// the browser controls. This helper sanitises those headers so a value like
// "evil.com\r\nSet-Cookie: x" or a "javascript:" scheme can never reach a URL
// or a cookie attribute, and enforces an optional host allowlist.
//
// The hard allowlist for *signed* URLs (the real token-leak risk) lives in the
// backend (app/services/trusted_proxy.py), which knows PUBLIC_URL / HOME_URL.
// This helper is the lighter frontend gate for redirects and cookies.

export type OriginInput = {
  host: string | null | undefined;
  proto: string | null | undefined;
};

// Anything with a header getter: a DOM Headers, a NextRequest's headers, or
// Next's ReadonlyHeaders from next/headers all satisfy this.
export type HeadersLike = { get(name: string): string | null };

export type OriginOpts = {
  // Canonical origin (e.g. "https://media.example.com"), used as the fallback
  // and added to the allowlist. Usually process.env.PUBLIC_URL.
  publicOrigin?: string | null;
  // Extra allowed hostnames (no port). Usually process.env.APP_ALLOWED_HOSTS.
  allowedHosts?: string[];
};

// host or host:port, or [ipv6] or [ipv6]:port, with no control chars/spaces.
const HOST_RE = /^[A-Za-z0-9._-]+(?::\d{1,5})?$|^\[[0-9A-Fa-f:]+\](?::\d{1,5})?$/;

function hostname(authority: string): string {
  const a = authority.trim().toLowerCase();
  if (a.startsWith("[") && a.includes("]")) return a.slice(1, a.indexOf("]"));
  if ((a.match(/:/g) ?? []).length === 1) return a.slice(0, a.lastIndexOf(":"));
  return a;
}

function isPrivateOrLoopback(host: string): boolean {
  if (host === "localhost") return true;
  // IPv6 loopback / ULA / link-local.
  if (host === "::1") return true;
  if (/^f[cd][0-9a-f]{2}:/i.test(host) || /^fe80:/i.test(host)) return true;
  // IPv4 literals: loopback, RFC1918, link-local.
  const m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  if (a > 255 || b > 255 || Number(m[3]) > 255 || Number(m[4]) > 255) return false;
  if (a === 127) return true;
  if (a === 10) return true;
  if (a === 192 && b === 168) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 169 && b === 254) return true;
  return false;
}

function originHost(origin: string | null | undefined): string | null {
  if (!origin) return null;
  try {
    return new URL(origin).hostname.toLowerCase();
  } catch {
    return null;
  }
}

function allowedHostSet(opts: OriginOpts): Set<string> {
  const set = new Set<string>(["localhost"]);
  const pub = originHost(opts.publicOrigin);
  if (pub) set.add(pub);
  for (const h of opts.allowedHosts ?? []) {
    const n = h.trim().toLowerCase();
    if (n) set.add(n);
  }
  return set;
}

function hostAllowed(authority: string, opts: OriginOpts): boolean {
  if (!authority || !HOST_RE.test(authority)) return false;
  const host = hostname(authority);
  if (!host) return false;
  if (allowedHostSet(opts).has(host)) return true;
  return isPrivateOrLoopback(host);
}

function sanitizeProto(proto: string | null | undefined, fallback: string): "http" | "https" {
  const p = (proto ?? "").split(",")[0].trim().toLowerCase();
  if (p === "http" || p === "https") return p;
  return fallback === "https" ? "https" : "http";
}

// Build a safe absolute origin ("proto://host") from request headers.
export function buildOrigin(input: OriginInput, opts: OriginOpts = {}): string {
  const fallbackOrigin = (opts.publicOrigin ?? "").trim() || "http://127.0.0.1:3001";
  let fallbackHost = "127.0.0.1:3001";
  let fallbackProto = "http";
  try {
    const u = new URL(fallbackOrigin);
    fallbackHost = u.host;
    fallbackProto = u.protocol.replace(":", "");
  } catch {
    // keep defaults
  }

  const rawHost = (input.host ?? "").split(",")[0].trim();
  const proto = sanitizeProto(input.proto, fallbackProto);
  if (hostAllowed(rawHost, opts)) {
    return `${proto}://${rawHost}`;
  }
  return `${fallbackProto}://${fallbackHost}`;
}

function envOpts(): OriginOpts {
  const allowed = (process.env.APP_ALLOWED_HOSTS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return { publicOrigin: process.env.PUBLIC_URL ?? null, allowedHosts: allowed };
}

// Convenience for Next request handlers: derive the site origin from a Headers
// object, trusting X-Forwarded-Host/Proto only after sanitising + allowlisting.
export function siteOriginFromHeaders(h: HeadersLike): string {
  return buildOrigin(
    { host: h.get("x-forwarded-host") ?? h.get("host"), proto: h.get("x-forwarded-proto") },
    envOpts(),
  );
}

// The scheme the request arrived over ("https" only when it genuinely did),
// used for the cookie Secure flag. Never trusts a non-http(s) value.
export function requestProto(h: HeadersLike): "http" | "https" {
  return sanitizeProto(h.get("x-forwarded-proto"), "http");
}
