/** Pure rules for saved library views on the app (the hook is
 * state/viewPrefs.ts). Views live on the server per user (GET /api/view-prefs,
 * PUT /api/view-prefs/<key>); the phone keeps a local copy so a screen opens
 * on the right view before the server answers, and offline. */

/** Same key format the server accepts. */
export const VIEW_KEY_RE = /^[a-z0-9][a-z0-9._:-]{0,63}$/;

export function isViewKey(key: string): boolean {
  return VIEW_KEY_RE.test(key);
}

/** Which value a screen should show: the server's when it has one that
 * passes `isValid`, else the local copy, else the default. */
export function resolveViewPref<T>(
  server: unknown,
  local: unknown,
  fallback: T,
  isValid: (v: unknown) => v is T = (v): v is T => v !== undefined && v !== null,
): T {
  if (isValid(server)) return server;
  if (isValid(local)) return local;
  return fallback;
}

/** A local choice the server never got (made offline, or before views moved
 * to the server) should be sent up once the server's views are known. */
export function shouldPushLocal(server: unknown, local: unknown): boolean {
  return (server === undefined || server === null) && local !== undefined && local !== null;
}
