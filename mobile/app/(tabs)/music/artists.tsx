import { useRouter } from "expo-router";
import React from "react";
import { View } from "react-native";

import { useArtists } from "@/api/queries";
import type { Artist } from "@/api/types";
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
import { useSortFilter } from "@/ui/useSortFilter";

const ARTIST_SORTS: SortOption<Artist>[] = [
  { key: "name", label: "Name", value: (a) => a.name },
  { key: "albums", label: "Albums", value: (a) => a.album_count },
];

// Filters (crit 39): catalogue depth.
const ARTIST_FILTERS: FilterOption<Artist>[] = [
  { key: "multi", label: "2+ albums", predicate: (a) => a.album_count >= 2 },
  { key: "single", label: "1 album", predicate: (a) => a.album_count === 1 },
];

/** Artists as photo tiles with their album count (like the PWA), 4 per row.
 * Rendered as a page and inline under the Music hub's Artists chip. */
export function ArtistsLibrary(): React.ReactElement {
  const artists = useArtists();
  const router = useRouter();
  const { columns, itemWidth } = useGrid();
  const sf = useSortFilter("artists", artists.data ?? [], ARTIST_SORTS, ARTIST_FILTERS);
  const { listRef, active, onSelect } = useAlphaRail(sf.items, (a) => a.name);

  return (
    <View style={libraryBody.pad}>
      <QueryState
        isLoading={artists.isLoading}
        isError={artists.isError}
        data={sf.items}
        onRetry={artists.refetch}
        isEmpty={() => (artists.data ?? []).length === 0}
        emptyTitle="No artists"
        emptyMessage="Your artists will appear here once your library syncs."
      >
        {(rows) => (
          <View style={{ flex: 1 }}>
            <SortFilterBar
              sorts={ARTIST_SORTS}
              sortKey={sf.state.sortKey}
              dir={sf.state.dir}
              filterKey={sf.state.filterKey}
              onSortKey={sf.setSortKey}
              onToggleDir={() => sf.setDir(toggleDir(sf.state.dir))}
              filters={ARTIST_FILTERS}
              filterLabel="Catalog"
              onFilterKey={sf.setFilterKey}
            />
            <RefreshableGrid
              listRef={listRef}
              data={rows}
              numColumns={columns}
              keyExtractor={(a) => a.id}
              refreshing={artists.isFetching}
              onRefresh={artists.refetch}
              renderItem={({ item }) => (
                <Tile
                  title={item.name}
                  subtitle={`${item.album_count} albums`}
                  artPath={item.image_path}
                  size={itemWidth}
                  compact
                  showSubtitle
                  onPress={() => router.push(`/music/artist/${item.id}`)}
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

export default function ArtistsScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Artists">
      <ArtistsLibrary />
    </LibraryScreen>
  );
}
