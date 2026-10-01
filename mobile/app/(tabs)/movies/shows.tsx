import { useRouter } from "expo-router";
import React, { useMemo } from "react";
import { View } from "react-native";

import { useContinueWatching, useShows } from "@/api/queries";
import type { Series } from "@/api/types";
import { AlphaRail } from "@/ui/AlphaRail";
import { PosterCard } from "@/ui/PosterCard";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { LibraryScreen, libraryBody } from "@/ui/LibraryScreen";
import type { FilterOption, SortOption } from "@/ui/sortFilter";
import { toggleDir } from "@/ui/sortFilter";
import { SortFilterBar } from "@/ui/SortFilterBar";
import { useAlphaRail } from "@/ui/useAlphaRail";
import { useGrid } from "@/ui/useGrid";
import { useSortFilter } from "@/ui/useSortFilter";

const SHOW_SORTS: SortOption<Series>[] = [
  { key: "title", label: "Title", value: (s) => s.title },
  { key: "year", label: "Year", value: (s) => s.year ?? null },
  { key: "added", label: "Date added", value: (s) => s.created_at ?? null },
];

/** Television: status chips (All / Watching / Complete / New) styled like the
 * PWA, sort, and a 4-per-row poster grid. Page + hub (TV Shows chip). */
export function ShowsLibrary(): React.ReactElement {
  const { columns, itemWidth } = useGrid();
  const shows = useShows();
  const cont = useContinueWatching();
  const router = useRouter();

  // "Watching" = shows with an in-progress episode (from continue-watching).
  // "New" = arrived in the last year. "Complete" = has episodes but nothing in
  // progress (best-effort without a per-series watched rollup endpoint).
  const watchingIds = useMemo(() => {
    const set = new Set<string>();
    for (const c of cont.data ?? []) if (c.kind === "series" || c.kind === "episode") set.add(c.id);
    return set;
  }, [cont.data]);

  const filters = useMemo<FilterOption<Series>[]>(() => {
    const thisYear = new Date().getFullYear();
    return [
      { key: "watching", label: "Watching", predicate: (s) => watchingIds.has(s.id) },
      { key: "complete", label: "Complete", predicate: (s) => !watchingIds.has(s.id) },
      { key: "new", label: "New", predicate: (s) => (s.year ?? 0) >= thisYear - 1 },
    ];
  }, [watchingIds]);

  const sf = useSortFilter("shows", shows.data ?? [], SHOW_SORTS, filters);
  const { listRef, active, onSelect } = useAlphaRail(sf.items, (s) => s.title);

  return (
    <View style={libraryBody.pad}>
      <QueryState
        isLoading={shows.isLoading}
        isError={shows.isError}
        data={sf.items}
        onRetry={shows.refetch}
        isEmpty={() => (shows.data ?? []).length === 0}
        emptyTitle="No shows"
        emptyMessage="Nothing matches this filter."
      >
        {(rows) => (
          <View style={{ flex: 1 }}>
            <SortFilterBar
              sorts={SHOW_SORTS}
              filters={filters}
              filterLabel="Status"
              sortKey={sf.state.sortKey}
              dir={sf.state.dir}
              filterKey={sf.state.filterKey}
              onSortKey={sf.setSortKey}
              onToggleDir={() => sf.setDir(toggleDir(sf.state.dir))}
              onFilterKey={sf.setFilterKey}
            />
            <RefreshableGrid
              listRef={listRef}
              data={rows}
              numColumns={columns}
              keyExtractor={(s) => s.id}
              refreshing={shows.isFetching}
              onRefresh={shows.refetch}
              renderItem={({ item }) => (
                <PosterCard
                  title={item.title}
                  meta={item.year ? String(item.year) : undefined}
                  artPath={item.poster_path}
                  width={itemWidth}
                  compact
                  onPress={() => router.push(`/movies/show/${item.id}`)}
                />
              )}
            />
            <AlphaRail active={active} onSelect={onSelect} />
          </View>
        )}
      </QueryState>
    </View>
  );
}

export default function ShowsScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Television">
      <ShowsLibrary />
    </LibraryScreen>
  );
}
