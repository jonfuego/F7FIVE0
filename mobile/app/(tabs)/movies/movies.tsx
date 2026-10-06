import { useRouter } from "expo-router";
import React, { useMemo } from "react";
import { View } from "react-native";

import { useAllProgress, useMovies } from "@/api/queries";
import type { Movie } from "@/api/types";
import { AlphaRail } from "@/ui/AlphaRail";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { ChipBar } from "@/ui/ChipBar";
import { LibraryScreen, libraryBody } from "@/ui/LibraryScreen";
import { PosterCard } from "@/ui/PosterCard";
import type { FilterOption, SortOption } from "@/ui/sortFilter";
import { toggleDir } from "@/ui/sortFilter";
import { SortFilterBar } from "@/ui/SortFilterBar";
import { useAlphaRail } from "@/ui/useAlphaRail";
import { useGrid } from "@/ui/useGrid";
import { useViewPref } from "@/state/viewPrefs";
import { isSortFilterState, sortFilterInitial, useSortFilter } from "@/ui/useSortFilter";

const MOVIE_SORTS: SortOption<Movie>[] = [
  { key: "title", label: "Title", value: (m) => m.title },
  { key: "year", label: "Year", value: (m) => m.year ?? null },
  { key: "runtime", label: "Runtime", value: (m) => m.runtime_min ?? null },
  { key: "added", label: "Date added", value: (m) => m.created_at ?? null },
  { key: "rating", label: "Rating", value: (m) => m.tmdb_rating ?? null },
];

const ALL_GENRES = "__all__";

function isGenre(v: unknown): v is string {
  return typeof v === "string" && v.length > 0 && v.length <= 64;
}

/** Movies: genre chips (like the PWA), status + sort, and a 4-per-row
 * poster grid with watched checks and resume bars. Rendered as a page and
 * inline under the Movies & Shows hub's Movies chip. */
export function MoviesLibrary(): React.ReactElement {
  const movies = useMovies();
  const router = useRouter();
  const progress = useAllProgress();
  const { columns, itemWidth } = useGrid();
  // Saved view (server, per user): the genre chip.
  const [genre, setGenre] = useViewPref("genre:movies", ALL_GENRES, isGenre);
  const genres = useMemo(() => {
    const set = new Set<string>();
    for (const m of movies.data ?? []) for (const g of m.genres ?? []) set.add(g);
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [movies.data]);
  const byFile = useMemo(() => {
    const map = new Map<string, { position_sec: number; duration_sec?: number | null; completed_at?: string | null }>();
    for (const p of progress.data ?? []) map.set(p.media_file_id, p);
    return map;
  }, [progress.data]);
  // Filters (crit 39): Plex's unwatched / in progress / watched, from the
  // user's progress rows keyed by media file.
  const filters = useMemo<FilterOption<Movie>[]>(() => {
    const done = new Set<string>();
    const started = new Set<string>();
    for (const p of progress.data ?? []) {
      if (p.completed_at) done.add(p.media_file_id);
      else if (p.position_sec > 0) started.add(p.media_file_id);
    }
    const files = (m: Movie) => (m.media_files ?? []).map((f) => f.id);
    return [
      { key: "unwatched", label: "Unwatched", predicate: (m) => !files(m).some((id) => done.has(id)) },
      { key: "inprogress", label: "In progress", predicate: (m) => files(m).some((id) => started.has(id)) },
      { key: "watched", label: "Watched", predicate: (m) => files(m).some((id) => done.has(id)) },
    ];
  }, [progress.data]);
  const inGenre = useMemo(
    () => (genre === ALL_GENRES ? movies.data ?? [] : (movies.data ?? []).filter((m) => (m.genres ?? []).includes(genre))),
    [movies.data, genre],
  );
  // Saved view (server, per user): this screen's sort and filter.
  const sortView = useViewPref("sort:movies", sortFilterInitial(MOVIE_SORTS), isSortFilterState);
  const sf = useSortFilter(sortView, inGenre, MOVIE_SORTS, filters);
  const { listRef, active, onSelect } = useAlphaRail(sf.items, (m) => m.title, columns);

  return (
    <View style={libraryBody.pad}>
      {genres.length > 0 ? (
        <View style={{ marginHorizontal: -16 }}>
          <ChipBar
            label="Genre"
            options={[{ key: ALL_GENRES, label: "All" }, ...genres.map((g) => ({ key: g, label: g }))]}
            value={genres.includes(genre) ? genre : ALL_GENRES}
            onChange={setGenre}
          />
        </View>
      ) : null}
      <QueryState
        isLoading={movies.isLoading}
        isError={movies.isError}
        data={sf.items}
        onRetry={movies.refetch}
        isEmpty={() => (movies.data ?? []).length === 0}
        emptyTitle="No movies"
        emptyMessage="Your movies will appear here once your library syncs."
      >
        {(rows) => (
          <View style={{ flex: 1 }}>
            <SortFilterBar
              sorts={MOVIE_SORTS}
              sortKey={sf.state.sortKey}
              dir={sf.state.dir}
              filterKey={sf.state.filterKey}
              onSortKey={sf.setSortKey}
              onToggleDir={() => sf.setDir(toggleDir(sf.state.dir))}
              filters={filters}
              filterLabel="Status"
              onFilterKey={sf.setFilterKey}
            />
            <RefreshableGrid
              listRef={listRef}
              data={rows}
              numColumns={columns}
              keyExtractor={(m) => m.id}
              refreshing={movies.isFetching}
              onRefresh={movies.refetch}
              renderItem={({ item }) => {
                const p = item.media_files?.[0] ? byFile.get(item.media_files[0].id) : undefined;
                const frac = p && !p.completed_at && p.duration_sec ? p.position_sec / p.duration_sec : 0;
                return (
                  <PosterCard
                    title={item.title}
                    meta={item.year ? String(item.year) : undefined}
                    artPath={item.poster_path}
                    width={itemWidth}
                    compact
                    watched={!!p?.completed_at}
                    progress={frac}
                    onPress={() => router.push(`/movies/movie/${item.id}`)}
                  />
                );
              }}
            />
            <AlphaRail active={active} onSelect={onSelect} />
          </View>
        )}
      </QueryState>
    </View>
  );
}

export default function MoviesScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Movies">
      <MoviesLibrary />
    </LibraryScreen>
  );
}
