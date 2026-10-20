// Pure rules for library-aware navigation on the phone and TV. Mirrors
// frontend/lib/library-nav.ts. No React or native imports, so it runs under
// jest in Node.
//
// A kind (movies, TV, music, music videos, podcasts) shows the names of its
// libraries only when more than one of them is visible to the user. With a
// single library the existing single tab already covers it.

export type LibraryKind =
  | "movies"
  | "tv"
  | "music"
  | "music_videos"
  | "podcasts";

export interface LibraryInfo {
  id: string;
  name: string;
  kind: string;
  sort_order: number;
}

export interface LibraryNavEntry {
  id: string;
  name: string;
  kind: string;
  sort_order: number;
}

/** The visible libraries of one kind, ordered by sort_order then name. */
export function librariesForKind(
  libraries: readonly LibraryInfo[],
  kind: string,
): LibraryInfo[] {
  return libraries
    .filter((l) => l.kind === kind)
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
}

/** A kind shows per-library names only when it has more than one library. */
export function kindShowsNames(
  libraries: readonly LibraryInfo[],
  kind: string,
): boolean {
  return librariesForKind(libraries, kind).length > 1;
}

/** Sub-nav entries for a kind: empty for zero or one library, one per library
 *  when the kind has more than one. */
export function libraryNavEntries(
  libraries: readonly LibraryInfo[],
  kind: string,
): LibraryNavEntry[] {
  const forKind = librariesForKind(libraries, kind);
  if (forKind.length <= 1) return [];
  return forKind.map((l) => ({
    id: l.id,
    name: l.name,
    kind: l.kind,
    sort_order: l.sort_order,
  }));
}

/** Every kind that has more than one visible library, in a stable order. */
export function kindsWithMultipleLibraries(
  libraries: readonly LibraryInfo[],
): string[] {
  const kinds: string[] = [];
  for (const l of libraries) {
    if (!kinds.includes(l.kind) && kindShowsNames(libraries, l.kind)) {
      kinds.push(l.kind);
    }
  }
  return kinds;
}
