import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";

import { useMusicVideoArtist } from "@/api/queries";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { Screen } from "@/ui/Screen";
import { Tile } from "@/ui/Tile";

/** Music video artist: their releases. */
export default function MusicVideoArtistScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const artist = useMusicVideoArtist(id ?? "");

  return (
    <Screen title={artist.data?.name ?? "Music Videos"}>
      <QueryState
        isLoading={artist.isLoading}
        isError={artist.isError}
        data={artist.data}
        onRetry={artist.refetch}
        isEmpty={(d) => d.releases.length === 0}
        emptyTitle="No releases"
        emptyMessage="This artist has no music video releases yet."
      >
        {(a) => (
          <RefreshableGrid
            data={a.releases}
            numColumns={2}
            keyExtractor={(r) => r.id}
            refreshing={artist.isFetching}
            onRefresh={artist.refetch}
            renderItem={({ item }) => (
              <Tile
                title={item.title}
                subtitle={[item.release_year, `${item.video_count} videos`].filter(Boolean).join(" · ")}
                artPath={item.cover_path}
                size={168}
                onPress={() => router.push(`/movies/mv-release/${item.id}`)}
              />
            )}
          />
        )}
      </QueryState>
    </Screen>
  );
}
