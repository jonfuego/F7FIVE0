// BFF proxy for POST /api/live/command (client -> server live-channel command).
//
// Swaps the httpOnly access cookie for the Bearer token and forwards the JSON
// command to the backend, mirroring the response. The SSE stream is one-way
// (server -> client); client actions come back over this POST.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const bodyText = await req.text();
  let body: unknown = {};
  if (bodyText.length > 0) {
    try {
      body = JSON.parse(bodyText);
    } catch {
      return NextResponse.json({ detail: "invalid_json_body" }, { status: 400 });
    }
  }

  const res = await backend("/api/live/command", {
    method: "POST",
    authed: true,
    body,
  });

  const payload = await res.text();
  return new NextResponse(payload, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}
