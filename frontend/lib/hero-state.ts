// Decides what the Home hero shows once the recent-items call settles.
// Pure so node:test can cover it (hero-state.test.ts). The hero must never
// sit on the loading skeleton after the data is in: an empty library gets a
// real empty state, a failed load gets an error with a retry, and a library
// with items gets the featured tile.
//
// Inputs mirror the page state: `recent` is null while the call is in
// flight and an array (possibly empty) once it resolves; `error` is a
// message string when the load failed.

export type HeroState =
  // The recent call is still in flight; show the skeleton.
  | { type: "loading" }
  // The call failed; show the message and offer a retry.
  | { type: "error"; message: string }
  // The call succeeded but the library has nothing playable yet.
  | { type: "empty" }
  // The call succeeded with items; the caller renders the featured tile.
  | { type: "ready" };

/**
 * Resolve the hero state from the loaded recent list and any load error.
 *
 * Order matters: an error wins even if a stale list is still around, then a
 * null list means the first load has not settled (skeleton), then an empty
 * list means a settled-but-empty library (empty state), else ready.
 */
export function resolveHeroState(
  recent: unknown[] | null,
  error: string | null,
): HeroState {
  if (error) return { type: "error", message: error };
  if (recent === null) return { type: "loading" };
  if (recent.length === 0) return { type: "empty" };
  return { type: "ready" };
}

/**
 * The empty-library copy. Admins get a nudge toward Admin; members get a
 * plain line. Wording is fixed by the UI punch list.
 */
export function heroEmptyMessage(isAdmin: boolean): string {
  return isAdmin
    ? "Add library folders in Admin to get started"
    : "Nothing here yet";
}
