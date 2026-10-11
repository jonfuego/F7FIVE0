// POST /api/session/refresh
//
// Rotates the access + refresh tokens using the refresh cookie. Used by
// the client-side fetch wrapper when it sees a 401, and by middleware
// when the access cookie has expired but the refresh cookie is still
// alive.
//
// Cookies are cleared ONLY when the backend answers 401 (reused, revoked,
// expired or unknown refresh token). A backend restart, a 5xx or an
// unreachable backend must not sign anyone out, so those answer 5xx and leave
// both cookies alone; the client retries (lib/refresh-outcome.ts).

import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { backend } from "@/lib/api";
import { REFRESH_COOKIE } from "@/lib/server-env";
import { clearSessionCookies, setSessionCookies } from "@/lib/cookies";
import { clearsSessionOnBackendStatus } from "@/lib/refresh-outcome";

export async function POST() {
  const refresh = (await cookies()).get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    const res = NextResponse.json({ detail: "no_refresh_cookie" }, { status: 401 });
    await clearSessionCookies(res);
    return res;
  }

  let backendRes: Response;
  try {
    backendRes = await backend("/api/auth/refresh", {
      method: "POST",
      body: { refresh_token: refresh },
    });
  } catch {
    // API down or restarting (connection refused / reset). Keep the cookies.
    return NextResponse.json({ detail: "backend_unreachable" }, { status: 503 });
  }
  const payload = await safeJson(backendRes);

  if (!backendRes.ok) {
    const res = NextResponse.json(payload ?? { detail: "refresh_failed" }, {
      status: backendRes.status,
    });
    if (clearsSessionOnBackendStatus(backendRes.status)) await clearSessionCookies(res);
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
    // Not a verdict on the session (a half-started API can answer oddly): 502,
    // cookies kept.
    return NextResponse.json({ detail: "malformed_token_response" }, { status: 502 });
  }

  const res = NextResponse.json({ ok: true }, { status: 200 });
  await setSessionCookies(res, {
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
