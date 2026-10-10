// BFF proxy for /api/art/*.
//
// The browser loads admin-pinned images via <img src="/api/art/<kind>/<id>/<role>?v=...">.
// This route attaches a Bearer before talking to the backend at /api/art/*,
// then streams the response back with its original content type.
//
// Auth: the Bearer comes from the shared accessBearer() helper in lib/api,
// the same cookie that backend(..., { authed: true }) attaches elsewhere. We
// never read the access cookie here and feed it to fetch, and we never call
// the API with no Bearer: when no token is available we answer 401 so the
// browser refreshes or signs in instead of getting a backend
// missing_bearer_token.
//
// Pass-through only. No path rewriting.
import { NextRequest, NextResponse } from "next/server";
import { API_ORIGIN } from "@/lib/server-env";
import { accessBearer } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: RouteContext) {
  const suffix = (await ctx.params).path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_ORIGIN}/api/art/${suffix}${search}`;

  const bearer = await accessBearer();
  if (!bearer) {
    // Never call the API with no Bearer. The <img> breaks and the browser
    // refreshes or signs in on its next data call.
    return NextResponse.json({ detail: "missing_bearer_token" }, { status: 401 });
  }

  const res = await fetch(url, {
    method: "GET",
    headers: { authorization: bearer },
    cache: "no-store",
    redirect: "manual",
  });

  // Stream the body back. Preserve content-type + cache headers so the
  // browser treats this the same as a static image.
  const headers = new Headers();
  const contentType = res.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const contentLength = res.headers.get("content-length");
  if (contentLength) headers.set("content-length", contentLength);
  // Cache-bust already lives in the query (?v=<set_at>), so we can let
  // the browser cache for a long time. Not critical if omitted.
  headers.set("cache-control", "private, max-age=3600");

  return new Response(res.body, {
    status: res.status,
    headers,
  });
}
