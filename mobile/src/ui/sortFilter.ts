/** Pure sort/filter primitives for library screens (crit 39). No native imports
 * so they unit test in Node. Each screen defines its sort options and (optional)
 * filter options; these functions apply a chosen sort/direction/filter to a list.
 * The chosen values are saved views per screen (useViewPref, server per user). */

export type SortDir = "asc" | "desc";

export interface SortOption<T> {
  /** Stable key stored in settings. */
  key: string;
  /** Human label for the bar. */
  label: string;
  /** Comparable value for an item (string or number). */
  value: (item: T) => string | number | null | undefined;
}

export interface FilterOption<T> {
  key: string;
  label: string;
  /** Keep the item when true. The "all" pseudo-filter is handled by a null key. */
  predicate: (item: T) => boolean;
}

/** Compare two sort values, nulls last, strings case-insensitively. */
export function compareValues(a: string | number | null | undefined, b: string | number | null | undefined): number {
  const an = a == null;
  const bn = b == null;
  if (an && bn) return 0;
  if (an) return 1; // nulls last
  if (bn) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).toLowerCase().localeCompare(String(b).toLowerCase());
}

/** Apply a sort (by option key + direction) and an optional filter (by key) to a
 * list. Returns a new array; the input is not mutated. Unknown keys are no-ops. */
export function applySortFilter<T>(
  items: T[],
  opts: {
    sorts: SortOption<T>[];
    filters?: FilterOption<T>[];
    sortKey: string;
    dir: SortDir;
    filterKey?: string | null;
  },
): T[] {
  let out = items;
  const filter = opts.filterKey ? opts.filters?.find((f) => f.key === opts.filterKey) : undefined;
  if (filter) out = out.filter((it) => filter.predicate(it));

  const sort = opts.sorts.find((s) => s.key === opts.sortKey);
  if (sort) {
    const sign = opts.dir === "desc" ? -1 : 1;
    out = [...out].sort((a, b) => {
      const av = sort.value(a);
      const bv = sort.value(b);
      // Nulls always sort last, independent of direction.
      const an = av == null;
      const bn = bv == null;
      if (an && bn) return 0;
      if (an) return 1;
      if (bn) return -1;
      return sign * compareValues(av, bv);
    });
  }
  return out;
}

/** Toggle a sort direction. */
export function toggleDir(dir: SortDir): SortDir {
  return dir === "asc" ? "desc" : "asc";
}
