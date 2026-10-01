// GET /api/session/me and PATCH /api/session/me
//
// GET returns the current user's profile if the access cookie is valid.
// PATCH updates self-service profile fields (display name for now). Both
// forward to /api/auth/me on the backend.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function GET() {
  const res = await backend("/api/auth/me", { method: "GET", authed: true });
  const payload = await safeJson(res);
  return NextResponse.json(payload ?? null, { status: res.status });
}

export async function PATCH(req: NextRequest) {
  const body = await safeJson(req);
  const res = await backend("/api/auth/me", {
    method: "PATCH",
    authed: true,
    body,
  });
  const payload = await safeJson(res);
  return NextResponse.json(payload ?? null, { status: res.status });
}

async function safeJson(res: Response | NextRequest): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
