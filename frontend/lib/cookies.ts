// Shared cookie helpers for the auth BFF.
//
// Both cookies are httpOnly so the browser JS bundle never sees the tokens.
// Secure follows the scheme the browser used: on behind HTTPS (Cloudflare
// Tunnel or a reverse proxy that sets X-Forwarded-Proto), off on a plain
// http://<lan-ip>:3001 install, where browsers would drop Secure cookies and
// login could never stick. COOKIE_SECURE=true|false overrides the check.
//
// SameSite=Lax keeps things simple: the player loads same-origin, so we
// don't need cross-site cookies, and the hls.js manifest rewrites already
// carry the signed query on every sub-fetch.

import { headers } from "next/headers";
import type { NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/server-env";

const IS_PROD = process.env.NODE_ENV === "production";

type CookieOpts = {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/";
  maxAge?: number;
};

function isSecureRequest(): boolean {
  const mode = (process.env.COOKIE_SECURE ?? "auto").toLowerCase();
  if (mode === "true") return true;
  if (mode === "false") return false;
  if (!IS_PROD) return false;
  try {
    const proto = (headers().get("x-forwarded-proto") ?? "").split(",")[0].trim();
    return proto === "https";
  } catch {
    return IS_PROD;
  }
}

function baseOpts(): CookieOpts {
  return { httpOnly: true, secure: isSecureRequest(), sameSite: "lax", path: "/" };
}

export function setSessionCookies(
  res: NextResponse,
  args: {
    access: string;
    accessTtlSeconds: number;
    refresh: string;
    refreshMaxAgeSeconds: number;
  },
): void {
  res.cookies.set(ACCESS_COOKIE, args.access, {
    ...baseOpts(),
    // Cap the access cookie TTL at the access JWT TTL. The refresh cookie
    // is what keeps the user logged in across access expirations.
    maxAge: Math.max(0, args.accessTtlSeconds),
  });
  res.cookies.set(REFRESH_COOKIE, args.refresh, {
    ...baseOpts(),
    maxAge: Math.max(0, args.refreshMaxAgeSeconds),
  });
}

export function clearSessionCookies(res: NextResponse): void {
  // maxAge 0 expires immediately on all browsers we care about.
  res.cookies.set(ACCESS_COOKIE, "", { ...baseOpts(), maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...baseOpts(), maxAge: 0 });
}
