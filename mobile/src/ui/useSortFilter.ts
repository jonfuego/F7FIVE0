import { useMemo } from "react";

import { applySortFilter, type FilterOption, type SortDir, type SortOption } from "./sortFilter";

export interface SortFilterState {
  sortKey: string;
  dir: SortDir;
  filterKey: string | null;
}

export interface UseSortFilterResult<T> {
  /** The sorted + filtered list. */
  items: T[];
  state: SortFilterState;
  setSortKey: (key: string) => void;
  setDir: (dir: SortDir) => void;
  setFilterKey: (key: string | null) => void;
}

/** The starting sort/filter for a screen: its first sort, ascending, no filter. */
export function sortFilterInitial<T>(
  sorts: SortOption<T>[],
  defaults?: Partial<SortFilterState>,
): SortFilterState {
  return {
    sortKey: defaults?.sortKey ?? sorts[0]?.key ?? "",
    dir: defaults?.dir ?? "asc",
    filterKey: defaults?.filterKey ?? null,
  };
}

/** Validator for a saved sort/filter view (drops anything malformed). */
export function isSortFilterState(v: unknown): v is SortFilterState {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.sortKey === "string" &&
    (o.dir === "asc" || o.dir === "desc") &&
    (o.filterKey === null || typeof o.filterKey === "string")
  );
}

/** Per-screen sort/filter. The state is a saved view the screen gets from
 * useViewPref (`sort:<screen>`, stored on the server per user so it follows
 * you across phone, web and TV). Pass that [state, setState], the screen's
 * sort options, optional filter options, and the raw list; get back the
 * sorted/filtered list plus setters. */
export function useSortFilter<T>(
  view: [SortFilterState, (s: SortFilterState) => void],
  items: T[],
  sorts: SortOption<T>[],
  filters?: FilterOption<T>[],
): UseSortFilterResult<T> {
  const [state, setState] = view;

  const sorted = useMemo(
    () =>
      applySortFilter(items, {
        sorts,
        filters,
        sortKey: state.sortKey,
        dir: state.dir,
        filterKey: state.filterKey,
      }),
    [items, sorts, filters, state.sortKey, state.dir, state.filterKey],
  );

  return {
    items: sorted,
    state,
    setSortKey: (sortKey) => setState({ ...state, sortKey }),
    setDir: (dir) => setState({ ...state, dir }),
    setFilterKey: (filterKey) => setState({ ...state, filterKey }),
  };
}
