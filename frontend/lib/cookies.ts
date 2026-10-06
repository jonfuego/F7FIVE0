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
import { requestProto } from "@/lib/origin";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/server-env";

const IS_PROD = process.env.NODE_ENV === "production";

type CookieOpts = {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/";
  maxAge?: number;
};

async function isSecureRequest(): Promise<boolean> {
  const mode = (process.env.COOKIE_SECURE ?? "auto").toLowerCase();
  if (mode === "true") return true;
  if (mode === "false") return false;
  if (!IS_PROD) return false;
  try {
    // Only trust a sanitised http/https value (SEC-P1-1); never a forged scheme.
    return requestProto(await headers()) === "https";
  } catch {
    return IS_PROD;
  }
}

async function baseOpts(): Promise<CookieOpts> {
  return { httpOnly: true, secure: await isSecureRequest(), sameSite: "lax", path: "/" };
}

export async function setSessionCookies(
  res: NextResponse,
  args: {
    access: string;
    accessTtlSeconds: number;
    refresh: string;
    refreshMaxAgeSeconds: number;
  },
): Promise<void> {
  const opts = await baseOpts();
  res.cookies.set(ACCESS_COOKIE, args.access, {
    ...opts,
    // Cap the access cookie TTL at the access JWT TTL. The refresh cookie
    // is what keeps the user logged in across access expirations.
    maxAge: Math.max(0, args.accessTtlSeconds),
  });
  res.cookies.set(REFRESH_COOKIE, args.refresh, {
    ...opts,
    maxAge: Math.max(0, args.refreshMaxAgeSeconds),
  });
}

export async function clearSessionCookies(res: NextResponse): Promise<void> {
  // maxAge 0 expires immediately on all browsers we care about.
  const opts = await baseOpts();
  res.cookies.set(ACCESS_COOKIE, "", { ...opts, maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...opts, maxAge: 0 });
}
