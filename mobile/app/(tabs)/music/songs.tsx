import React, { useMemo, useState } from "react";
import { View } from "react-native";

import { useSongs } from "@/api/queries";
import { usePlayer } from "@/player/PlayerProvider";
import { useTrackRadio } from "@/player/useTrackRadio";
import { useDownloads } from "@/download/DownloadProvider";
import { songEntry } from "@/download/entries";
import { AlbumTileMenu } from "@/ui/AlbumTileMenu";
import { AlphaRail } from "@/ui/AlphaRail";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { LibraryScreen, libraryBody } from "@/ui/LibraryScreen";
import type { FilterOption, SortOption } from "@/ui/sortFilter";
import { SortFilterBar } from "@/ui/SortFilterBar";
import { TrackRow } from "@/ui/TrackRow";
import { toggleDir } from "@/ui/sortFilter";
import { useAlphaRail } from "@/ui/useAlphaRail";
import { useViewPref } from "@/state/viewPrefs";
import { isSortFilterState, sortFilterInitial, useSortFilter } from "@/ui/useSortFilter";
import type { SongRow } from "@/api/types";

const SONG_SORTS: SortOption<SongRow>[] = [
  { key: "title", label: "Title", value: (s) => s.title },
  { key: "artist", label: "Artist", value: (s) => s.artist_name },
  { key: "album", label: "Album", value: (s) => s.album_title },
  { key: "duration", label: "Length", value: (s) => s.duration_sec ?? 0 },
];

/** Songs list with sort/filter, A-Z rail and the song menu. Rendered as a
 * page and inline under the Music hub's Songs chip. */
export function SongsLibrary(): React.ReactElement {
  const songs = useSongs();
  const { playSongs, playNext, addToQueue, nowPlaying } = usePlayer();
  const startTrackRadio = useTrackRadio();
  const { enqueue, state: dl } = useDownloads();
  const [menuFor, setMenuFor] = useState<SongRow | null>(null);
  // Filters (crit 39): downloaded for offline, and long tracks.
  const filters = useMemo<FilterOption<SongRow>[]>(() => {
    const done = new Set(dl.items.filter((i) => i.status === "done").map((i) => i.id));
    return [
      { key: "downloaded", label: "Downloaded", predicate: (s) => !!s.media_files[0] && done.has(s.media_files[0].id) },
      { key: "long", label: "8+ min", predicate: (s) => (s.duration_sec ?? 0) >= 480 },
    ];
  }, [dl.items]);
  // Saved view (server, per user): this screen's sort and filter.
  const sortView = useViewPref("sort:songs", sortFilterInitial(SONG_SORTS), isSortFilterState);
  const sf = useSortFilter(sortView, songs.data ?? [], SONG_SORTS, filters);
  const { listRef, active, onSelect } = useAlphaRail(sf.items, (s) => s.title);

  return (
    <View style={libraryBody.pad}>
      <QueryState
        isLoading={songs.isLoading}
        isError={songs.isError}
        data={sf.items}
        onRetry={songs.refetch}
        isEmpty={() => (songs.data ?? []).length === 0}
        emptyTitle="No songs"
        emptyMessage="Your songs will appear here once your library syncs."
      >
        {(rows) => (
          <View style={{ flex: 1 }}>
            <SortFilterBar
              sorts={SONG_SORTS}
              sortKey={sf.state.sortKey}
              dir={sf.state.dir}
              filterKey={sf.state.filterKey}
              onSortKey={sf.setSortKey}
              onToggleDir={() => sf.setDir(toggleDir(sf.state.dir))}
              filters={filters}
              filterLabel="Show"
              onFilterKey={sf.setFilterKey}
            />
            <RefreshableGrid
              listRef={listRef}
              data={rows}
              keyExtractor={(s) => s.id}
              refreshing={songs.isFetching}
              onRefresh={songs.refetch}
              renderItem={({ item, index }) => (
                <TrackRow
                  title={item.title}
                  subtitle={`${item.artist_name} · ${item.album_title}`}
                  artPath={item.cover_path}
                  active={nowPlaying?.mediaFileId === item.media_files[0]?.id}
                  onPress={() => playSongs(rows, index)}
                  onLongPress={() => setMenuFor(item)}
                  menu={{ song: item, playSongs, playNext, addToQueue }}
                />
              )}
            />
            <AlphaRail active={active} onSelect={onSelect} />
          </View>
        )}
      </QueryState>
      <AlbumTileMenu
        visible={!!menuFor}
        title={menuFor?.title}
        onPlayNow={() => menuFor && void playSongs([menuFor], 0)}
        onPlayNext={() => menuFor && void playNext([menuFor])}
        onAddToQueue={() => menuFor && void addToQueue([menuFor])}
        onShuffle={() => menuFor && void playSongs([menuFor], 0)}
        onTrackRadio={() => menuFor && void startTrackRadio(menuFor.id)}
        onDownload={() => {
          const e = menuFor ? songEntry(menuFor) : null;
          if (e) enqueue(e.mediaFileId, e.title, e.opts);
        }}
        onClose={() => setMenuFor(null)}
      />
    </View>
  );
}

export default function SongsScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Songs">
      <SongsLibrary />
    </LibraryScreen>
  );
}
