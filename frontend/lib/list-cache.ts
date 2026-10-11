// In-memory copy of a library list (the Movies list today), kept for the life
// of the browser tab so a page you come back to can paint its tiles at once
// instead of showing placeholders until the list is fetched again.
//
// This is a plain JS Map: nothing is written to disk, there is no service
// worker, IndexedDB or CDN involved, and a full page load starts empty. Art
// stays in the browser's own HTTP cache (private, immutable, `?v=` key).
//
// Rules the pages follow (see pickListLoad):
// - A copy younger than LIST_FRESH_MS is used as is, with no request.
// - An older copy is painted first, then the page asks again and swaps the
//   new list in (stale while revalidate).
// - Anything that changes a list entry on the server (the edit modals) calls
//   invalidateLists(); a folder scan finishing or an explicit reload bypasses
//   the copy with `force`.

export const LIST_FRESH_MS = 30_000;

type Entry = { at: number; data: unknown };

const store = new Map<string, Entry>();

export type CachedList<T> = { data: T; ageMs: number };

export function getList<T>(key: string, now: number = Date.now()): CachedList<T> | null {
  const e = store.get(key);
  if (!e) return null;
  return { data: e.data as T, ageMs: Math.max(0, now - e.at) };
}

export function setList(key: string, data: unknown, now: number = Date.now()): void {
  store.set(key, { at: now, data });
}

/** Drop one list, or every list when no key is given. */
export function invalidateLists(key?: string): void {
  if (key === undefined) store.clear();
  else store.delete(key);
}

/** What a page does on mount. */
export type ListLoad =
  | { paint: false; fetch: true } // nothing cached: placeholders, then fetch
  | { paint: true; fetch: false } // fresh copy: paint it, no request
  | { paint: true; fetch: true }; // old copy: paint it, then fetch

export function pickListLoad(
  cached: { ageMs: number } | null,
  opts: { force?: boolean; freshMs?: number } = {},
): ListLoad {
  const freshMs = opts.freshMs ?? LIST_FRESH_MS;
  if (!cached) return { paint: false, fetch: true };
  if (opts.force || cached.ageMs >= freshMs) return { paint: true, fetch: true };
  return { paint: true, fetch: false };
}
