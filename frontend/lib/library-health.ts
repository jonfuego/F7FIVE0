// Admin > Library health: wording and small pure helpers (kept apart from the
// React page so node:test can cover them; see library-health.test.ts).

/** Per-kind counts as GET /api/admin/library/health returns them. */
export type KindCounts = Record<string, number>;

const KIND_ORDER = ["movie", "series", "artist", "album"] as const;

const KIND_LABEL: Record<string, [string, string]> = {
  movie: ["movie", "movies"],
  series: ["TV show", "TV shows"],
  artist: ["artist", "artists"],
  album: ["album", "albums"],
};

/** Sum of every kind in an unmatched / missing_art map. */
export function kindTotal(counts: KindCounts | null | undefined): number {
  if (!counts) return 0;
  let total = 0;
  for (const v of Object.values(counts)) {
    if (typeof v === "number" && Number.isFinite(v)) total += v;
  }
  return total;
}

/**
 * "1 movie, 1 TV show, 5 artists, 3 albums": the non-zero kinds in a fixed
 * order (known kinds first, any other kind after, by name). Empty when every
 * kind is zero.
 */
export function kindBreakdown(counts: KindCounts | null | undefined): string {
  if (!counts) return "";
  const known = KIND_ORDER.filter((k) => k in counts);
  const other = Object.keys(counts)
    .filter((k) => !(KIND_ORDER as readonly string[]).includes(k))
    .sort();
  const parts: string[] = [];
  for (const k of [...known, ...other]) {
    const n = counts[k];
    if (typeof n !== "number" || !Number.isFinite(n) || n <= 0) continue;
    const [one, many] = KIND_LABEL[k] ?? [k, k];
    parts.push(`${n} ${n === 1 ? one : many}`);
  }
  return parts.join(", ");
}

/**
 * What the page says when the eligible list is empty. The list only holds
 * files missing 7 or more days in a reachable folder, so with newer missing
 * files the old "No missing files eligible for cleanup." read as if the
 * Missing files count were wrong.
 */
export function emptyMissingListText(missingTotal: number): string {
  if (missingTotal <= 0) return "No missing files.";
  const files = missingTotal === 1 ? "1 file is" : `${missingTotal} files are`;
  return (
    `${files} missing, none eligible for cleanup yet. A missing file is listed ` +
    "here once it has been missing for 7 days and its library folder is reachable."
  );
}
