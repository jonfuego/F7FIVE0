// BFF proxy for POST /api/admin/updates/upload (Admin > Updates > Upload a Setup).
//
// This shadows the generic /api/admin/[...path] proxy because the body is a
// whole Setup exe (hundreds of MB), not JSON: the generic proxy reads the body
// as text. The body is streamed straight through to the API, never buffered.
//
// proxy.ts skips this exact path (see its matcher): Next buffers at most 10 MB
// of a request body that passes through the proxy and would cut a Setup off.
// So the one check the proxy makes for a cookie-authed, state-changing call, a
// same-origin guard, is made here. The API does the rest: it needs the admin
// bearer, then the admin's own password (x-confirm-password) before it reads
// a byte of the body.
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { API_ORIGIN, ACCESS_COOKIE } from "@/lib/server-env";
import { siteOriginFromHeaders } from "@/lib/origin";
import { isForbiddenCrossOrigin } from "@/lib/security-headers";

export const dynamic = "force-dynamic";

const API_PATH = "/api/admin/updates/upload";

export async function POST(req: NextRequest): Promise<NextResponse> {
  if (
    isForbiddenCrossOrigin({
      method: "POST",
      pathname: API_PATH,
      origin: req.headers.get("origin"),
      selfOrigin: siteOriginFromHeaders(req.headers),
      hasBearer: false,
    })
  ) {
    return NextResponse.json({ detail: "bad_origin" }, { status: 403 });
  }

  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;
  if (!access) {
    // Same answer the API gives, so the browser wrapper refreshes and retries.
    return NextResponse.json({ detail: "missing_bearer_token" }, { status: 401 });
  }

  const headers = new Headers();
  headers.set("authorization", `Bearer ${access}`);
  for (const name of ["content-type", "content-length", "x-confirm-password"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }

  const init: RequestInit & { duplex?: "half" } = {
    method: "POST",
    headers,
    body: req.body ?? undefined,
    cache: "no-store",
    redirect: "manual",
    // Node fetch requires duplex:"half" when streaming a request body.
    duplex: "half",
  };

  let res: Response;
  try {
    res = await fetch(`${API_ORIGIN}${API_PATH}`, init);
  } catch {
    return NextResponse.json({ detail: "api_unreachable" }, { status: 502 });
  }
  const payload = await res.text();
  return new NextResponse(payload, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
