// BFF catch-all proxy for /api/admin/*.
//
// Attaches the Bearer token from the httpOnly access cookie before
// calling the backend. Admin-only endpoints require_admin on the
// backend side, so non-admins just bounce off a 403.
//
// Path translation:
//   /api/admin/users/...                       -> backend /api/auth/users/...               (admin user mgmt)
//   /api/admin/library/sync                    -> backend /api/sync/run                     (trigger *arr sync)
//   /api/admin/library/music-videos            -> backend /api/sync/music-videos            (trigger filesystem scan)
//   /api/admin/library/series/{id}/rescan      -> backend /api/series/{id}/rescan           (rescan one series folder)
//   /api/admin/<anything else>                 -> backend /api/admin/<same>                 (admin read endpoints)
//
// The alias shape keeps the browser's URL space tidy: everything the
// admin UI needs is under one prefix.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = { params: { path: string[] } };

function backendPath(suffix: string): string {
  if (suffix === "library/sync" || suffix === "library/sync/") {
    // Backend sync endpoint lives on the library router, which is mounted
    // at prefix="/api" (not "/api/library"), so the path is /api/sync/run.
    return "/api/sync/run";
  }
  if (
    suffix === "library/music-videos" ||
    suffix === "library/music-videos/"
  ) {
    // Music videos scan is filesystem-only (not *arr), but the endpoint
    // lives on the same library router alongside /sync/run.
    return "/api/sync/music-videos";
  }
  // Per-series Sonarr rescan. The library router holds it beside /sync/run,
  // so strip the `library/` prefix to hit /api/series/{id}/rescan.
  const rescanMatch = suffix.match(/^library\/(series\/[^\/]+\/rescan)\/?$/);
  if (rescanMatch) {
    return `/api/${rescanMatch[1]}`;
  }
  if (suffix.startsWith("users")) {
    return `/api/auth/${suffix}`;
  }
  return `/api/admin/${suffix}`;
}

async function forward(
  req: NextRequest,
  ctx: RouteContext,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
): Promise<NextResponse> {
  const suffix = ctx.params.path.join("/");
  const search = req.nextUrl.search;
  const path = `${backendPath(suffix)}${search}`;

  let body: unknown;
  if (method === "POST" || method === "PUT" || method === "PATCH") {
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

export async function GET(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "GET");
}
export async function POST(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "POST");
}
export async function PATCH(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "PATCH");
}
export async function PUT(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "PUT");
}
export async function DELETE(req: NextRequest, ctx: RouteContext) {
  return forward(req, ctx, "DELETE");
}
