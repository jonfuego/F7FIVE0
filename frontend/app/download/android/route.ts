// Android app download for signed-in browsers.
//
// The APK lives with the API, which stamps every download with this server's
// addresses so the app fills in the server on first launch (see
// backend/app/services/android_app.py). This route asks the API for a signed
// one-hour link with the session's access token and redirects the browser to
// it. The link (/api/client/android-app/download?...) is proxied straight to
// the API by proxy.ts, so the file never passes through Next.
//
// ?abi=armv7 picks the 32-bit build when a release has one.
//
// HEAD answers with the file name, version and size (or 404 when no APK is
// published) without a redirect. The Account page and gear menu use it to
// show or hide the download.

import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { backend } from "@/lib/api";
import { setSessionCookies } from "@/lib/cookies";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/server-env";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type AppInfo = {
  available: boolean;
  version?: string;
  file_name?: string;
  size_bytes?: number;
  path?: string;
  abis?: string[];
};

type Tokens = {
  access_token: string;
  refresh_token: string;
  expires_in_seconds?: number;
  refresh_expires_in_seconds?: number;
};

function infoPath(req: NextRequest): string {
  const abi = req.nextUrl.searchParams.get("abi") === "armv7" ? "armv7" : "arm64";
  return `/api/client/android-app?abi=${abi}`;
}

async function fetchInfo(path: string, access: string | undefined): Promise<Response> {
  return backend(path, {
    method: "GET",
    headers: access ? { authorization: `Bearer ${access}` } : undefined,
  });
}

// One refresh attempt when the access cookie has expired. Returns the new
// tokens (to set on the response) or null.
async function refreshTokens(): Promise<Tokens | null> {
  const refresh = (await cookies()).get(REFRESH_COOKIE)?.value;
  if (!refresh) return null;
  const res = await backend("/api/auth/refresh", {
    method: "POST",
    body: { refresh_token: refresh },
  });
  if (!res.ok) return null;
  const body = (await res.json().catch(() => null)) as Partial<Tokens> | null;
  if (!body || typeof body.access_token !== "string" || typeof body.refresh_token !== "string") {
    return null;
  }
  return body as Tokens;
}

async function lookup(req: NextRequest): Promise<{ info: AppInfo | null; status: number; tokens: Tokens | null }> {
  const path = infoPath(req);
  let res = await fetchInfo(path, (await cookies()).get(ACCESS_COOKIE)?.value);
  let tokens: Tokens | null = null;
  if (res.status === 401) {
    tokens = await refreshTokens();
    if (tokens) res = await fetchInfo(path, tokens.access_token);
  }
  if (!res.ok) return { info: null, status: res.status, tokens };
  return { info: (await res.json()) as AppInfo, status: 200, tokens };
}

async function withTokens(res: NextResponse, tokens: Tokens | null): Promise<NextResponse> {
  if (tokens) {
    await setSessionCookies(res, {
      access: tokens.access_token,
      accessTtlSeconds: tokens.expires_in_seconds ?? 900,
      refresh: tokens.refresh_token,
      refreshMaxAgeSeconds: tokens.refresh_expires_in_seconds ?? 60 * 60 * 24 * 29,
    });
  }
  return res;
}

function notPublished(): NextResponse {
  return new NextResponse("The Android app has not been published on this server yet.", {
    status: 404,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
  });
}

export async function HEAD(req: NextRequest): Promise<Response> {
  const { info, status, tokens } = await lookup(req);
  if (status === 401) return new NextResponse(null, { status: 401 });
  if (!info?.available) return withTokens(new NextResponse(null, { status: 404 }), tokens);
  const headers = new Headers({
    "content-type": "application/vnd.android.package-archive",
    "cache-control": "private, no-store",
    "x-apk-name": info.file_name ?? "F7FIVE0.apk",
    "x-apk-version": info.version ?? "",
    "x-apk-abis": (info.abis ?? []).join(","),
  });
  if (info.size_bytes) headers.set("content-length", String(info.size_bytes));
  return withTokens(new NextResponse(null, { status: 200, headers }), tokens);
}

export async function GET(req: NextRequest): Promise<Response> {
  const { info, status, tokens } = await lookup(req);
  if (status === 401) {
    // Session gone: sign in, then come straight back here.
    const host = req.headers.get("host") ?? req.nextUrl.host;
    const proto = req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "");
    const login = new URL(`${proto}://${host}/login`);
    login.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
    return NextResponse.redirect(login);
  }
  if (!info?.available || !info.path) return withTokens(notPublished(), tokens);
  // Relative Location: the browser stays on whatever address it used, which
  // is also the address the API stamps as "where this was downloaded from".
  return withTokens(
    new NextResponse(null, { status: 302, headers: { location: info.path, "cache-control": "no-store" } }),
    tokens,
  );
}
