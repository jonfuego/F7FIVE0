// BFF proxy for POST /api/library/podcasts/episodes/{id}/stream.
//
// Swaps the browser httpOnly access cookie for the Bearer the backend wants, and
// rewrites the absolute stream URL it returns into a same-origin path (the
// backend builds it from the request host; on loopback that is a port the browser
// cannot reach). The path-only URL resolves against whatever origin the page was
// loaded from, so it works the same through a tunnel and in dev. Same idea as
// /api/stream/start.
import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ id: string }> };

export async function POST(_req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  const { id } = await ctx.params;
  if (!/^[0-9a-fA-F-]{36}$/.test(id)) {
    return NextResponse.json({ detail: "invalid_episode_id" }, { status: 400 });
  }
  const res = await backend(`/api/podcasts/episodes/${id}/stream`, { method: "POST", authed: true, body: {} });
  if (!res.ok) {
    return new NextResponse(await res.text(), {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  }
  const payload = (await res.json()) as { url?: unknown } & Record<string, unknown>;
  payload.url = toSameOrigin(typeof payload.url === "string" ? payload.url : "");
  // The signed art URL is for header-less loaders on the phone; the page uses cover_path.
  delete payload.art_url;
  return NextResponse.json(payload);
}

// "http://127.0.0.1:8002/stream/podcast/x?uid=..." -> "/stream/podcast/x?uid=..."
function toSameOrigin(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}
