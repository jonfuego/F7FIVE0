// BFF proxy for GET /api/live (the live-channel Server-Sent Events stream).
//
// The browser's EventSource sends the httpOnly session cookie but cannot set an
// Authorization header, so this route swaps the cookie for the Bearer token the
// backend expects, opens the long-lived text/event-stream to the API, and
// streams its body straight back to the browser unchanged.
//
// Why SSE and not WebSockets: the single-origin proxy (proxy.ts) forwards
// requests with NextResponse.rewrite, which carries a long HTTP response but
// not the WebSocket Upgrade handshake. See docs/realtime.md.

import { NextRequest } from "next/server";
import { cookies } from "next/headers";
import { API_ORIGIN, ACCESS_COOKIE } from "@/lib/server-env";

export const dynamic = "force-dynamic";
// Never buffer an SSE stream; frames must flush as they arrive.
export const fetchCache = "force-no-store";

export async function GET(req: NextRequest): Promise<Response> {
  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;

  const headers = new Headers();
  headers.set("accept", "text/event-stream");
  if (access) headers.set("authorization", `Bearer ${access}`);

  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/api/live`, {
      method: "GET",
      headers,
      // Abort the upstream fetch when the browser disconnects so the backend
      // generator is cancelled and the subscriber is dropped.
      signal: req.signal,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return new Response("event: error\ndata: upstream_unavailable\n\n", {
      status: 502,
      headers: { "content-type": "text/event-stream" },
    });
  }

  if (!upstream.ok || upstream.body === null) {
    // Mirror the auth/other error so the client's EventSource onerror fires and
    // its reconnect-with-backoff kicks in (or it bounces to login on 401).
    const text = await upstream.text().catch(() => "");
    return new Response(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
