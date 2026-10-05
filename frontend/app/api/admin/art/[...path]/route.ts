// BFF proxy for /api/admin/art/*.
//
// This shadows the generic /api/admin/[...path] proxy because uploads
// here are multipart/form-data, not JSON. The generic proxy parses
// `await req.text()` as JSON and would mangle the multipart body.
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
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { API_ORIGIN, ACCESS_COOKIE } from "@/lib/server-env";

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

  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;

  const headers = new Headers();
  if (access) headers.set("authorization", `Bearer ${access}`);
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
