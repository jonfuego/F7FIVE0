import { useRouter } from "expo-router";
import React from "react";
import { View } from "react-native";

import { useAlbums } from "@/api/queries";
import type { Album } from "@/api/types";
import { AlphaRail } from "@/ui/AlphaRail";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { LibraryScreen, libraryBody } from "@/ui/LibraryScreen";
import type { FilterOption, SortOption } from "@/ui/sortFilter";
import { toggleDir } from "@/ui/sortFilter";
import { SortFilterBar } from "@/ui/SortFilterBar";
import { Tile } from "@/ui/Tile";
import { useAlphaRail } from "@/ui/useAlphaRail";
import { useGrid } from "@/ui/useGrid";
import { useViewPref } from "@/state/viewPrefs";
import { isSortFilterState, sortFilterInitial, useSortFilter } from "@/ui/useSortFilter";

const ALBUM_SORTS: SortOption<Album>[] = [
  { key: "title", label: "Title", value: (a) => a.title },
  { key: "artist", label: "Artist", value: (a) => a.artist_name ?? "" },
  { key: "released", label: "Released", value: (a) => a.release_date ?? "" },
  { key: "added", label: "Date added", value: (a) => a.created_at ?? null },
];

const isType = (a: Album, t: string) => (a.album_type ?? "album").toLowerCase() === t;

// Filters (crit 39): release type from Lidarr's albumType.
const ALBUM_FILTERS: FilterOption<Album>[] = [
  { key: "albums", label: "LPs", predicate: (a) => isType(a, "album") },
  { key: "eps", label: "EPs", predicate: (a) => isType(a, "ep") },
  { key: "singles", label: "Singles", predicate: (a) => isType(a, "single") },
];

/** Albums grid (4 per row on a phone), sort/filter + A-Z rail. Rendered as a
 * page (default export) and inline under the Music hub's Albums chip. */
export function AlbumsLibrary(): React.ReactElement {
  const albums = useAlbums();
  const router = useRouter();
  const { columns, itemWidth } = useGrid();
  // Saved view (server, per user): this screen's sort and filter.
  const sortView = useViewPref("sort:albums", sortFilterInitial(ALBUM_SORTS), isSortFilterState);
  const sf = useSortFilter(sortView, albums.data ?? [], ALBUM_SORTS, ALBUM_FILTERS);
  const { listRef, active, onSelect } = useAlphaRail(sf.items, (a) => a.title, columns);

  return (
    <View style={libraryBody.pad}>
      <QueryState
        isLoading={albums.isLoading}
        isError={albums.isError}
        data={sf.items}
        onRetry={albums.refetch}
        isEmpty={() => (albums.data ?? []).length === 0}
        emptyTitle="No albums"
        emptyMessage="Your albums will appear here once your library syncs."
      >
        {(rows) => (
          <View style={{ flex: 1 }}>
            <SortFilterBar
              sorts={ALBUM_SORTS}
              sortKey={sf.state.sortKey}
              dir={sf.state.dir}
              filterKey={sf.state.filterKey}
              onSortKey={sf.setSortKey}
              onToggleDir={() => sf.setDir(toggleDir(sf.state.dir))}
              filters={ALBUM_FILTERS}
              filterLabel="Type"
              onFilterKey={sf.setFilterKey}
            />
            <RefreshableGrid
              listRef={listRef}
              data={rows}
              numColumns={columns}
              keyExtractor={(a) => a.id}
              refreshing={albums.isFetching}
              onRefresh={albums.refetch}
              renderItem={({ item }) => (
                <Tile
                  title={item.title}
                  subtitle={item.artist_name}
                  artPath={item.cover_path}
                  size={itemWidth}
                  compact
                  onPress={() => router.push(`/music/album/${item.id}`)}
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

export default function AlbumsScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Albums">
      <AlbumsLibrary />
    </LibraryScreen>
  );
}
