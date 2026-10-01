// POST /api/session/me/password
//
// Self-service password change. Forwards to /api/auth/me/password on the
// backend. A successful change revokes every outstanding session on the
// backend, so the UI layer is expected to send the user back to /login
// after the 204 lands.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function POST(req: NextRequest) {
  const body = await safeJson(req);
  const res = await backend("/api/auth/me/password", {
    method: "POST",
    authed: true,
    body,
  });
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const payload = await safeJson(res);
  return NextResponse.json(payload ?? null, { status: res.status });
}

async function safeJson(r: NextRequest | Response): Promise<unknown> {
  try {
    return await r.json();
  } catch {
    return null;
  }
}
