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

/** Fetch the visible libraries. Any failure or non-array answer returns []. */
export async function loadLibraries(get: LibrariesFetcher): Promise<LibraryInfo[]> {
  try {
    const data = await get(LIBRARIES_PATH);
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
  } catch {
    return [];
  }
}
