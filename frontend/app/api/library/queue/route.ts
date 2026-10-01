// BFF passthrough for the per-user audio queue.
//
// Browser path:  /api/library/queue
// Backend path:  /api/queue/   (the library namespace exists only on the
// browser side; this proxy strips it the same way the library catch-all
// does and forwards with the Bearer token.)
//
// Network failures here must not throw to the user; the queue context
// in lib/queue.tsx already swallows write errors and relies on the
// localStorage write-through plus the next debounced PUT.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

const BACKEND_PATH = "/api/queue/";

async function forward(
  req: NextRequest,
  method: "GET" | "PUT" | "DELETE",
): Promise<NextResponse> {
  let body: unknown;
  if (method === "PUT") {
    const text = await req.text();
    body = text.length > 0 ? JSON.parse(text) : undefined;
  }

  const res = await backend(BACKEND_PATH, {
    method,
    authed: true,
    body,
  });

  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const payload = await res.text();
  const contentType = res.headers.get("content-type") ?? "application/json";
  return new NextResponse(payload, {
    status: res.status,
    headers: { "content-type": contentType },
  });
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  return forward(req, "GET");
}

export async function PUT(req: NextRequest): Promise<NextResponse> {
  return forward(req, "PUT");
}

export async function DELETE(req: NextRequest): Promise<NextResponse> {
  return forward(req, "DELETE");
}
