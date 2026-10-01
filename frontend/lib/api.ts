// Server-only fetch helper for talking to the F7FIVE0-API backend.
//
// Usage from a route handler or server component:
//
//   const res = await backend("/api/auth/me", { method: "GET", authed: true });
//   if (!res.ok) return NextResponse.json(await res.json(), { status: res.status });
//
// Set `authed: true` to attach the current access token from cookies. Set
// `authed: false` (the default) for login/refresh calls that carry their
// own credentials in the body.

import { cookies } from "next/headers";
import { API_ORIGIN, ACCESS_COOKIE } from "@/lib/server-env";

type BackendInit = Omit<RequestInit, "body"> & {
  body?: unknown;
  authed?: boolean;
};

export async function backend(path: string, init: BackendInit = {}): Promise<Response> {
  const url = `${API_ORIGIN}${path.startsWith("/") ? path : `/${path}`}`;

  const headers = new Headers(init.headers ?? {});
  if (init.body !== undefined && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (init.authed) {
    const jar = cookies();
    const access = jar.get(ACCESS_COOKIE)?.value;
    if (access) headers.set("authorization", `Bearer ${access}`);
  }

  return fetch(url, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    // Loopback call. Next's default cache for GETs would stale the /me check.
    cache: "no-store",
    redirect: "manual",
  });
}
