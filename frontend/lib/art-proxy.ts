// Header handling for the /api/art BFF route, kept pure so node:test can
// cover it without Next.
//
// Request: the Bearer is attached by the route; If-None-Match is forwarded so
// a browser revalidation can be answered 304 by the API.
// Response: the API's Cache-Control and ETag are passed through unchanged (the
// API already says `private, max-age=31536000, immutable`; every art URL
// carries ?v=<set_at>, so a re-pick changes the URL). Making the browser's
// disk cache the persistent cache is the point; do not shorten it here.

export function artUpstreamHeaders(
  bearer: string,
  incoming: Headers,
): Record<string, string> {
  const headers: Record<string, string> = { authorization: bearer };
  const inm = incoming.get("if-none-match");
  if (inm) headers["if-none-match"] = inm;
  return headers;
}

export function artResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers();
  for (const name of ["content-type", "content-length", "cache-control", "etag"]) {
    const value = upstream.get(name);
    if (value) headers.set(name, value);
  }
  // Art is behind sign-in: never let a shared cache keep it, even if the
  // upstream header were ever missing.
  if (!headers.has("cache-control")) headers.set("cache-control", "private, no-cache");
  return headers;
}
