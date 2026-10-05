// BFF proxy for /api/art/*.
//
// The browser loads admin-pinned images via <img src="/api/art/<kind>/<id>/<role>?v=...">.
// This route pulls the access cookie and adds a Bearer header before
// talking to the backend at /api/art/*, then streams the response back
// with its original content type.
//
// Pass-through only. No path rewriting.
import { cookies } from "next/headers";
import { NextRequest } from "next/server";
import { API_ORIGIN, ACCESS_COOKIE } from "@/lib/server-env";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: RouteContext) {
  const suffix = (await ctx.params).path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_ORIGIN}/api/art/${suffix}${search}`;

  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;

  const res = await fetch(url, {
    method: "GET",
    headers: access
      ? { authorization: `Bearer ${access}` }
      : undefined,
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
