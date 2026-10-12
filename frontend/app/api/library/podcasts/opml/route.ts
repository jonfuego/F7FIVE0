// BFF proxy for /api/library/podcasts/opml (OPML import and export).
//
// It shadows the generic /api/library/[...path] proxy because neither side is
// JSON: the export is an XML download and the import is a multipart upload.
// The upload is streamed straight to the API with the Bearer from the httpOnly
// access cookie (the browser never holds it); the API caps it at 1 MB. The
// same-origin guard for a cookie-authed, state-changing call runs in proxy.ts.
import { NextRequest, NextResponse } from "next/server";
import { accessBearer, backend } from "@/lib/api";
import { API_ORIGIN } from "@/lib/server-env";

export const dynamic = "force-dynamic";

const API_PATH = "/api/podcasts/opml";

export async function GET(): Promise<NextResponse> {
  const res = await backend(API_PATH, { method: "GET", authed: true });
  if (!res.ok) {
    return new NextResponse(await res.text(), {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  }
  return new NextResponse(await res.text(), {
    status: 200,
    headers: {
      "content-type": res.headers.get("content-type") ?? "text/x-opml+xml; charset=utf-8",
      "content-disposition": res.headers.get("content-disposition") ?? 'attachment; filename="f7five0-podcasts.opml"',
      "cache-control": "no-store",
    },
  });
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const bearer = await accessBearer();
  if (!bearer) {
    // Same answer the API gives, so the browser wrapper refreshes and retries.
    return NextResponse.json({ detail: "missing_bearer_token" }, { status: 401 });
  }
  const headers = new Headers({ authorization: bearer });
  for (const name of ["content-type", "content-length"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const init: RequestInit & { duplex?: "half" } = {
    method: "POST",
    headers,
    body: req.body ?? undefined,
    cache: "no-store",
    redirect: "manual",
    duplex: "half",
  };
  let res: Response;
  try {
    res = await fetch(`${API_ORIGIN}${API_PATH}`, init);
  } catch {
    return NextResponse.json({ detail: "api_unreachable" }, { status: 502 });
  }
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}
