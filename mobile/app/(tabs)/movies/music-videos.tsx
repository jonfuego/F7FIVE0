import { useRouter } from "expo-router";
import React from "react";
import { View } from "react-native";

import { useMusicVideoArtists } from "@/api/queries";
import type { MusicVideoArtist } from "@/api/types";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { LibraryScreen, libraryBody } from "@/ui/LibraryScreen";
import { useGrid } from "@/ui/useGrid";
import type { FilterOption, SortOption } from "@/ui/sortFilter";
import { toggleDir } from "@/ui/sortFilter";
import { SortFilterBar } from "@/ui/SortFilterBar";
import { Tile } from "@/ui/Tile";
import { useViewPref } from "@/state/viewPrefs";
import { isSortFilterState, sortFilterInitial, useSortFilter } from "@/ui/useSortFilter";

const MV_SORTS: SortOption<MusicVideoArtist>[] = [
  { key: "name", label: "Name", value: (a) => a.name },
  { key: "videos", label: "Videos", value: (a) => a.video_count },
];

// Filters (crit 39): catalogue depth.
const MV_FILTERS: FilterOption<MusicVideoArtist>[] = [
  { key: "multi", label: "3+ videos", predicate: (a) => a.video_count >= 3 },
  { key: "few", label: "1-2 videos", predicate: (a) => a.video_count < 3 },
];

/** Music video artists as photo tiles with video counts, 4 per row. Page +
 * hub (Music Videos chip). */
export function MusicVideosLibrary(): React.ReactElement {
  const artists = useMusicVideoArtists();
  const router = useRouter();
  const { columns, itemWidth } = useGrid(false);
  // Saved view (server, per user): this screen's sort and filter.
  const sortView = useViewPref("sort:music-videos", sortFilterInitial(MV_SORTS), isSortFilterState);
  const sf = useSortFilter(sortView, artists.data ?? [], MV_SORTS, MV_FILTERS);

  return (
    <View style={libraryBody.pad}>
      <QueryState
        isLoading={artists.isLoading}
        isError={artists.isError}
        data={sf.items}
        onRetry={artists.refetch}
        isEmpty={() => (artists.data ?? []).length === 0}
        emptyTitle="No music videos"
        emptyMessage="Your music videos will appear here once your library syncs."
      >
        {(rows) => (
          <View style={{ flex: 1 }}>
            <SortFilterBar
              sorts={MV_SORTS}
              sortKey={sf.state.sortKey}
              dir={sf.state.dir}
              filterKey={sf.state.filterKey}
              onSortKey={sf.setSortKey}
              onToggleDir={() => sf.setDir(toggleDir(sf.state.dir))}
              filters={MV_FILTERS}
              filterLabel="Catalog"
              onFilterKey={sf.setFilterKey}
            />
            <RefreshableGrid
            data={rows}
            numColumns={columns}
            keyExtractor={(a) => a.id}
            refreshing={artists.isFetching}
            onRefresh={artists.refetch}
            renderItem={({ item }) => (
              <Tile
                title={item.name}
                subtitle={`${item.video_count} videos`}
                artPath={item.image_path}
                size={itemWidth}
                compact
                showSubtitle
                onPress={() => router.push(`/movies/mv-artist/${item.id}`)}
              />
            )}
            />
          </View>
        )}
      </QueryState>
    </View>
  );
}

export default function MusicVideosScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Music Videos">
      <MusicVideosLibrary />
    </LibraryScreen>
  );
}
