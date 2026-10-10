// BFF proxy for /api/admin/art/*.
//
// This shadows the generic /api/admin/[...path] proxy because uploads
// here are multipart/form-data, not JSON. The generic proxy parses
// `await req.text()` as JSON and would mangle the multipart body, so we
// stream the raw body straight through instead.
//
// Auth: the Bearer comes from the shared accessBearer() helper in lib/api,
// the same cookie that backend(..., { authed: true }) attaches for the
// generic proxy. We never read the access cookie here and feed it to fetch,
// and we never call the API with no Bearer: when no token is available we
// answer 401 so the browser refreshes or signs in. This is the fix for the
// art window losing its sign-in (missing_bearer_token) once the 15-min
// access token had expired.
//
// Pass-through path: no rewriting. The backend route is also at
// /api/admin/art/<kind>/<id>/<role>.
//
// Methods:
//   POST  (multipart)  -> raw forward
//   POST  /from-url    (JSON)
//   POST  /from-search (JSON, Slice B)
//   DELETE
//   GET   /search      (Slice B)
import { NextRequest, NextResponse } from "next/server";
import { API_ORIGIN } from "@/lib/server-env";
import { accessBearer } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function forward(
  req: NextRequest,
  ctx: RouteContext,
  method: string,
): Promise<NextResponse> {
  const suffix = (await ctx.params).path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_ORIGIN}/api/admin/art/${suffix}${search}`;

  const bearer = await accessBearer();
  if (!bearer) {
    // Same answer the API gives, so the browser refreshes and retries or
    // signs in. Never call the API with no Bearer.
    return NextResponse.json({ detail: "missing_bearer_token" }, { status: 401 });
  }

  const headers = new Headers();
  headers.set("authorization", bearer);
  // Preserve the client's content-type so FastAPI's multipart parser
  // can read the boundary from it. For JSON bodies this is equally
  // important: if we drop it, FastAPI will 422.
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);

  // Pass the body through as a raw stream. For GET/DELETE this is
  // undefined, which fetch accepts.
  const hasBody = method === "POST" || method === "PUT" || method === "PATCH";
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    cache: "no-store",
    redirect: "manual",
  };
  if (hasBody) {
    init.body = req.body ?? undefined;
    // Node fetch requires duplex:"half" when streaming a body.
    init.duplex = "half";
  }

  const res = await fetch(url, init);

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

export async function GET(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "GET");
}
export async function POST(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "POST");
}
export async function DELETE(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "DELETE");
}
