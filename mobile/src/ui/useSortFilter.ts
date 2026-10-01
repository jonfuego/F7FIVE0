import { useMemo } from "react";

import { useSetting } from "@/state/settings";
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

/** Per-screen sort/filter with persistence (crit 39). Choices are stored under
 * `sort:<screen>` via useSetting (AsyncStorage, no tokens). Pass the screen's
 * sort options, optional filter options, and the raw list; get back the
 * sorted/filtered list plus setters wired to persistence. */
export function useSortFilter<T>(
  screen: string,
  items: T[],
  sorts: SortOption<T>[],
  filters?: FilterOption<T>[],
  defaults?: Partial<SortFilterState>,
): UseSortFilterResult<T> {
  const initial: SortFilterState = {
    sortKey: defaults?.sortKey ?? sorts[0]?.key ?? "",
    dir: defaults?.dir ?? "asc",
    filterKey: defaults?.filterKey ?? null,
  };
  const [state, setState] = useSetting<SortFilterState>(`sort:${screen}`, initial);

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
