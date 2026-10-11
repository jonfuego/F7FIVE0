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
import { artResponseHeaders, artUpstreamHeaders } from "@/lib/art-proxy";

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
    headers: artUpstreamHeaders(bearer, req.headers),
    cache: "no-store",
    redirect: "manual",
  });

  // Stream the body back. The API's content-type, cache-control and etag
  // pass through unchanged (a 304 included), so the browser's disk cache keeps
  // posters across visits.
  const headers = artResponseHeaders(res.headers);

  // A 304 has no body.
  return new Response(res.status === 304 ? null : res.body, {
    status: res.status,
    headers,
  });
}
