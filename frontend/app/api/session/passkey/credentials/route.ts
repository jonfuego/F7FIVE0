// GET /api/session/passkey/credentials
//
// Authenticated. Lists the signed-in user's passkeys by proxying to the backend
// /api/auth/passkeys. Returns only labels + timestamps (never key material).

import { NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function GET(): Promise<Response> {
  const res = await backend("/api/auth/passkeys", { method: "GET", authed: true });
  const payload = await res.json().catch(() => null);
  return NextResponse.json(payload ?? { detail: "passkey_list_failed" }, {
    status: res.status,
  });
}
