// POST /api/session/passkey/login/verify
//
// Unauthenticated. Forwards the WebAuthn assertion to the backend
// /api/auth/passkey/login/verify. On success the backend returns the same
// TokenPair shape as password login; this route stores the tokens in httpOnly
// cookies exactly like /api/session/login, so browser JS never sees them.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";
import { setSessionCookies } from "@/lib/cookies";

export async function POST(req: NextRequest): Promise<Response> {
  let body: { credential?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "invalid_json" }, { status: 400 });
  }
  if (!body.credential || typeof body.credential !== "object") {
    return NextResponse.json({ detail: "missing_credential" }, { status: 400 });
  }

  const ua = req.headers.get("user-agent") ?? "";
  // Installed-PWA shells get the long refresh window, same as password login.
  const clientType = req.headers.get("x-client-type") ?? "browser";

  const fwdHeaders: Record<string, string> = {};
  if (ua) fwdHeaders["user-agent"] = ua;

  const backendRes = await backend("/api/auth/passkey/login/verify", {
    method: "POST",
    headers: Object.keys(fwdHeaders).length ? fwdHeaders : undefined,
    body: {
      credential: body.credential,
      client_type: clientType === "pwa" ? "pwa" : "browser",
      device_name: ua.slice(0, 80) || null,
    },
  });

  const payload = await safeJson(backendRes);
  if (!backendRes.ok) {
    return NextResponse.json(payload ?? { detail: "passkey_login_failed" }, {
      status: backendRes.status,
    });
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
    return NextResponse.json({ detail: "malformed_token_response" }, { status: 502 });
  }

  const meRes = await backend("/api/auth/me", {
    method: "GET",
    headers: { authorization: `Bearer ${access_token}` },
  });
  const me = meRes.ok ? await safeJson(meRes) : null;

  const res = NextResponse.json({ user: me }, { status: 200 });
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
