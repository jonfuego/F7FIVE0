// BFF proxy for GET /api/libraries.
//
// Returns the signed-in user's visible libraries. Attaches the Bearer token
// from the httpOnly access cookie so the browser bundle never sees the token.
// The backend route is /api/libraries (library router, mounted at /api).

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest): Promise<NextResponse> {
  const res = await backend("/api/libraries", { method: "GET", authed: true });
  const payload = await res.text();
  const contentType = res.headers.get("content-type") ?? "application/json";
  return new NextResponse(payload, {
    status: res.status,
    headers: { "content-type": contentType },
  });
}
