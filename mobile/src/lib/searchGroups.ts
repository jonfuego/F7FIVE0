/** Pure grouping for the Search screen. The API returns one flat list; the
 * screen shows it under headers: Artists, then Albums, then Songs, then any
 * other kind the API sends (in the order each kind first appears). Empty
 * groups are never produced, and rows keep their API order inside a group. */

export const GROUP_ORDER = ["artist", "album", "song"] as const;

const GROUP_TITLES: Record<string, string> = {
  artist: "Artists",
  album: "Albums",
  song: "Songs",
  movie: "Movies",
  series: "Shows",
};

export interface SearchGroup<T extends { kind: string }> {
  kind: string;
  title: string;
  data: T[];
}

/** Header text for a kind. Unknown kinds get a plain plural of their name. */
export function groupTitle(kind: string): string {
  const known = GROUP_TITLES[kind];
  if (known) return known;
  const name = kind.trim() || "other";
  return `${name.charAt(0).toUpperCase()}${name.slice(1)}s`;
}

export function groupSearchResults<T extends { kind: string }>(
  results: readonly T[] | null | undefined,
): SearchGroup<T>[] {
  const byKind = new Map<string, T[]>();
  for (const row of results ?? []) {
    const bucket = byKind.get(row.kind);
    if (bucket) bucket.push(row);
    else byKind.set(row.kind, [row]);
  }
  const ordered: string[] = [];
  for (const kind of GROUP_ORDER) {
    if (byKind.has(kind)) ordered.push(kind);
  }
  // Map keeps insertion order, so extra kinds follow first appearance.
  for (const kind of byKind.keys()) {
    if (!(GROUP_ORDER as readonly string[]).includes(kind)) ordered.push(kind);
  }
  return ordered.map((kind) => ({
    kind,
    title: groupTitle(kind),
    data: byKind.get(kind) as T[],
  }));
}
