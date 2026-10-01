// BFF catch-all proxy for /api/requests/*.
//
// Swaps the browser's httpOnly access cookie for the Bearer token the
// backend expects, then forwards to the FastAPI requests router, which is
// mounted at prefix="/api/requests" (so the path passes through unchanged,
// same shape as the browser URL). Same cookie-to-Bearer pattern as the
// library catch-all.
//
// The tunnel must route ^/api/requests/.* to this Next server (3001),
// placed before the broad ^/api/.* rule. See cloudflared/config.yml.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = { params: { path: string[] } };

async function forward(
  req: NextRequest,
  ctx: RouteContext,
  method: "GET" | "POST" | "PUT" | "DELETE",
): Promise<NextResponse> {
  const suffix = ctx.params.path.join("/");
  const search = req.nextUrl.search;
  const path = `/api/requests/${suffix}${search}`;

  let body: unknown;
  if (method === "POST" || method === "PUT") {
    const text = await req.text();
    body = text.length > 0 ? JSON.parse(text) : undefined;
  }

  const res = await backend(path, { method, authed: true, body });

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

export async function GET(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return forward(req, ctx, "GET");
}

export async function POST(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return forward(req, ctx, "POST");
}

export async function PUT(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return forward(req, ctx, "PUT");
}

export async function DELETE(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return forward(req, ctx, "DELETE");
}
