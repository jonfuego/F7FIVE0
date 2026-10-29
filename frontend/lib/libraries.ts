// Loads the signed-in user's visible libraries from the BFF.
//
// Takes the fetcher as an argument (like lib/artist-radio.ts) so it stays
// testable and React-free. The BFF route is /api/libraries, which forwards to
// the backend's GET /api/libraries with the user's Bearer token attached.

import type { LibraryInfo } from "./library-nav.ts";

export const LIBRARIES_PATH = "/api/libraries";

export type LibrariesFetcher = (
  path: string,
) => Promise<unknown>;

/** Normalize the backend's answer, a bare `[{id, name, kind, sort_order}]`
 * array. Anything that is not an array (an object wrapper included) is []. */
export function parseLibraries(data: unknown): LibraryInfo[] {
  if (!Array.isArray(data)) return [];
  return data
    .filter((d): d is Record<string, unknown> => !!d && typeof d === "object")
    .map((d) => ({
      id: String(d.id ?? ""),
      name: String(d.name ?? ""),
      kind: String(d.kind ?? ""),
      sort_order: Number(d.sort_order ?? 0),
    }))
    .filter((l) => l.id && l.kind);
}

/** The kinds Admin > Organizer works on. */
export const ORGANIZER_KINDS: readonly string[] = ["movies", "tv", "music"];

/** The libraries Admin > Organizer lists: movies, TV and music only. */
export function organizerLibraries(libraries: readonly LibraryInfo[]): LibraryInfo[] {
  return libraries.filter((l) => ORGANIZER_KINDS.includes(l.kind));
}

/** Fetch the visible libraries. Any failure or non-array answer returns []. */
export async function loadLibraries(get: LibrariesFetcher): Promise<LibraryInfo[]> {
  try {
    return parseLibraries(await get(LIBRARIES_PATH));
  } catch {
    return [];
  }
}
