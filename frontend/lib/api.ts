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
import { bearerFromCookieValue } from "@/lib/auth-bearer";

type BackendInit = Omit<RequestInit, "body"> & {
  body?: unknown;
  authed?: boolean;
};

// Re-export the pure Bearer builder so callers can import both from lib/api.
export { bearerFromCookieValue };

// The one place a route reads the httpOnly access cookie. Routes that cannot go
// through backend() (streamed multipart bodies) use this to get the same Bearer
// backend() attaches, then forward the raw body themselves. A null result means
// no token is available, so the route must answer 401 and let the browser
// refresh or sign in. The token never reaches the browser.
export async function accessBearer(): Promise<string | null> {
  const jar = await cookies();
  return bearerFromCookieValue(jar.get(ACCESS_COOKIE)?.value);
}

export async function backend(path: string, init: BackendInit = {}): Promise<Response> {
  const url = `${API_ORIGIN}${path.startsWith("/") ? path : `/${path}`}`;

  const headers = new Headers(init.headers ?? {});
  if (init.body !== undefined && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (init.authed) {
    const bearer = await accessBearer();
    if (bearer) headers.set("authorization", bearer);
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
