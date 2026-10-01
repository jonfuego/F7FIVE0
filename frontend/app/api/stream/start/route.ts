// BFF proxy for POST /api/stream/start.
//
// Two responsibilities:
//   1. Swap the browser's httpOnly access cookie for the Bearer token the
//      backend expects.
//   2. Rewrite the absolute stream URL the backend returns into a
//      same-origin path-only URL. The backend builds its URL from the
//      incoming Host header, and on loopback that ends up as
//      http://127.0.0.1:8002 which the browser can't reach. A path-only
//      URL resolves against whatever origin the page was loaded from, so
//      it works identically in prod (through the tunnel) and in dev.

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

  const res = await backend("/api/stream/start", {
    method: "POST",
    authed: true,
    body,
  });

  if (!res.ok) {
    // Mirror the error verbatim; the client shows it.
    const payload = await res.text();
    return new NextResponse(payload, {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") ?? "application/json",
      },
    });
  }

  const payload = (await res.json()) as { url?: unknown } & Record<string, unknown>;
  const urlValue = typeof payload.url === "string" ? payload.url : "";
  payload.url = toSameOrigin(urlValue);

  return NextResponse.json(payload);
}

// "http://127.0.0.1:8002/stream/foo?uid=x" -> "/stream/foo?uid=x"
// Leaves already-relative URLs untouched.
function toSameOrigin(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}
