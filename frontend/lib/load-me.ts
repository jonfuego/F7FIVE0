// Loads the signed-in user's profile for the Admin and Account pages.
//
// Both pages used to load /api/session/me with a raw fetch(). On first
// navigation after the ~15-min access token had expired, the BFF returned
// 401, the raw fetch did not refresh, and the page was left with a null
// profile: an indefinite blank skeleton (Admin) or a bare error line on an
// otherwise empty page (Account). A manual browser reload fixed it only
// because the reload path re-minted the token.
//
// Routing the load through the shared apiGet gives it the single-flight
// /api/session/refresh + retry, so the page renders on the first navigation
// even right after the token expired. If the refresh cookie is dead apiGet
// bounces to /login; any other failure throws so the caller can show a
// retryable error state instead of a silent blank.
//
// The getter is passed in (the pages pass apiGet) so node:test can drive this
// without resolving the "@/" path alias. Same pattern as lib/overrides.ts.

export type Me = {
  id: string;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

export type Getter = <T>(path: string, opts?: { signal?: AbortSignal }) => Promise<T>;

export function loadMe(get: Getter, signal?: AbortSignal): Promise<Me | null> {
  return get<Me | null>("/api/session/me", { signal });
}
