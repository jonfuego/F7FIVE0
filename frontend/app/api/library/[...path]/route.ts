// BFF catch-all proxy for /api/library/*.
//
// Forwards the authenticated browser call to the backend's FastAPI library
// router, attaching the Bearer token from the httpOnly access cookie. The
// browser bundle never sees the token; the browser calls Next, Next calls
// the backend.
//
// Path translation: the library router is mounted at prefix="/api" on the
// backend (not "/api/library"), so "/api/library/movies" on the browser
// side maps to "/api/movies" on the backend. The `library/` namespace
// exists only to keep the browser URL space organized and give this BFF
// a route to own.
//
// If the access token is expired, the client wrapper (lib/client-api.ts)
// hits /api/session/refresh and retries. We return backend status codes
// verbatim so that flow works.
//
// Methods: GET (reads), POST (admin sync), PUT (progress upsert),
// DELETE (progress clear).

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function forward(
  req: NextRequest,
  ctx: RouteContext,
  method: "GET" | "POST" | "PUT" | "DELETE",
): Promise<NextResponse> {
  const suffix = (await ctx.params).path.join("/");
  // Preserve the query string — list endpoints use limit/offset/q.
  const search = req.nextUrl.search;
  // Strip the browser-side "library/" namespace; backend router is at /api.
  const path = `/api/${suffix}${search}`;

  // GET / DELETE do not carry a JSON body. POST / PUT do.
  let body: unknown;
  if (method === "POST" || method === "PUT") {
    const text = await req.text();
    body = text.length > 0 ? JSON.parse(text) : undefined;
  }

  const res = await backend(path, {
    method,
    authed: true,
    body,
  });

  // Mirror status + content type. 204s have no body.
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
