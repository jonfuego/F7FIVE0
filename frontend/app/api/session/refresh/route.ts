// POST /api/session/refresh
//
// Rotates the access + refresh tokens using the refresh cookie. Used by
// the client-side fetch wrapper when it sees a 401, and by middleware
// when the access cookie has expired but the refresh cookie is still
// alive.
//
// On a reused-or-revoked refresh the backend returns 401 and we clear
// both cookies so the UI can redirect to /login.

import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { backend } from "@/lib/api";
import { REFRESH_COOKIE } from "@/lib/server-env";
import { clearSessionCookies, setSessionCookies } from "@/lib/cookies";

export async function POST() {
  const refresh = cookies().get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    const res = NextResponse.json({ detail: "no_refresh_cookie" }, { status: 401 });
    clearSessionCookies(res);
    return res;
  }

  const backendRes = await backend("/api/auth/refresh", {
    method: "POST",
    body: { refresh_token: refresh },
  });
  const payload = await safeJson(backendRes);

  if (!backendRes.ok) {
    const res = NextResponse.json(payload ?? { detail: "refresh_failed" }, {
      status: backendRes.status,
    });
    clearSessionCookies(res);
    return res;
  }

  const {
    access_token,
    refresh_token,
    expires_in_seconds,
    refresh_expires_in_seconds,
  } = (payload ?? {}) as {
    access_token?: unknown;
    refresh_token?: unknown;
    expires_in_seconds?: unknown;
    refresh_expires_in_seconds?: unknown;
  };
  if (typeof access_token !== "string" || typeof refresh_token !== "string") {
    const res = NextResponse.json({ detail: "malformed_token_response" }, { status: 502 });
    clearSessionCookies(res);
    return res;
  }

  const res = NextResponse.json({ ok: true }, { status: 200 });
  setSessionCookies(res, {
    access: access_token,
    accessTtlSeconds: typeof expires_in_seconds === "number" ? expires_in_seconds : 900,
    refresh: refresh_token,
    refreshMaxAgeSeconds:
      typeof refresh_expires_in_seconds === "number"
        ? refresh_expires_in_seconds
        : 60 * 60 * 24 * 29,
  });
  return res;
}

async function safeJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
