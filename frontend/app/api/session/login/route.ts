// POST /api/session/login
//
// Accepts {username, password} from the browser. Forwards to the backend
// /api/auth/login and stores the returned access + refresh tokens in
// httpOnly cookies. Browser JS never sees the raw tokens.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";
import { setSessionCookies } from "@/lib/cookies";

type LoginBody = { username?: unknown; password?: unknown };

export async function POST(req: NextRequest) {
  let body: LoginBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "invalid_json" }, { status: 400 });
  }

  const username =
    typeof body.username === "string" ? body.username.trim().toLowerCase() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!username || !password) {
    return NextResponse.json({ detail: "missing_credentials" }, { status: 400 });
  }

  // Pass the user-agent through so the backend auth_events log matches
  // what the user's browser will send on every other request.
  const ua = req.headers.get("user-agent") ?? "";
  // Forward the PWA hint set by the login page. Anything other than "pwa"
  // ends up as "browser" on the backend.
  const clientType = req.headers.get("x-client-type") ?? "";

  const fwdHeaders: Record<string, string> = {};
  if (ua) fwdHeaders["user-agent"] = ua;
  if (clientType) fwdHeaders["x-client-type"] = clientType;

  const backendRes = await backend("/api/auth/login", {
    method: "POST",
    headers: Object.keys(fwdHeaders).length ? fwdHeaders : undefined,
    body: {
      username,
      password,
      // Keep the device label informative but not noisy. UA prefix is plenty.
      device_label: ua.slice(0, 80) || null,
    },
  });

  const payload = await safeJson(backendRes);
  if (!backendRes.ok) {
    // Preserve the backend status (401 for bad creds, etc.) so the client
    // can distinguish "wrong password" from "server is down".
    return NextResponse.json(payload ?? { detail: "login_failed" }, {
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

  // Pull the user profile in the same round-trip so the client can render
  // display name and role without a second call.
  const meRes = await backend("/api/auth/me", {
    method: "GET",
    headers: { authorization: `Bearer ${access_token}` },
  });
  const me = meRes.ok ? await safeJson(meRes) : null;

  const res = NextResponse.json({ user: me }, { status: 200 });
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
