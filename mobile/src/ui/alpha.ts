/** Pure A-Z bucketing helpers for the alpha rail. No native/expo imports so the
 * jest suite can exercise them in Node (see AlphaRail.tsx for the component). */

/** Normalize a title to its alpha bucket letter (articles sort under the next
 * word, matching the PWA AlphaRail: "The Matrix" -> M). */
export function alphaBucket(title: string): string {
  const t = (title ?? "").trim().replace(/^(the|a|an)\s+/i, "");
  const c = t.charAt(0).toUpperCase();
  return c >= "A" && c <= "Z" ? c : "#";
}

/** Build the ordered set of section letters present in a set of titles, and a
 * map from letter to the index of its first item. Powers scroll-to-letter. */
export function buildAlphaIndex(titles: string[]): { letters: Set<string>; firstIndex: Record<string, number> } {
  const letters = new Set<string>();
  const firstIndex: Record<string, number> = {};
  titles.forEach((t, i) => {
    const b = alphaBucket(t);
    letters.add(b);
    if (!(b in firstIndex)) firstIndex[b] = i;
  });
  return { letters, firstIndex };
}

/** FlatList row that holds item `index` in a grid of `numColumns`. */
export function rowForItem(index: number, numColumns: number): number {
  return Math.floor(index / Math.max(1, numColumns));
}
