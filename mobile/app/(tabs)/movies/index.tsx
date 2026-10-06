import { useRouter } from "expo-router";
import React, { useMemo } from "react";
import { ScrollView, StyleSheet } from "react-native";

import { useContinueWatching, useMovies, useMusicVideoArtists, useShows } from "@/api/queries";
import { ContinueWatchingCard } from "@/ui/ContinueWatchingCard";
import { HubScreen } from "@/ui/HubScreen";
import { MarqueeHeader } from "@/ui/MarqueeHeader";
import { PosterCard } from "@/ui/PosterCard";
import { Rail } from "@/ui/Rail";
import { Tile } from "@/ui/Tile";
import { MoviesLibrary } from "./movies";
import { MusicVideosLibrary } from "./music-videos";
import { ShowsLibrary } from "./shows";

const RAIL_POSTER = 100;

function newest<T extends { created_at?: string | null }>(items: T[] | undefined, n = 20): T[] {
  return [...(items ?? [])].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")).slice(0, n);
}

/** Movies & Shows "All" view: continue watching, newest movies and shows, and
 * music video artists, each with SEE ALL into its grid (Plex-style landing). */
function VideoAll({ select }: { select: (key: string) => void }): React.ReactElement {
  const router = useRouter();
  const cont = useContinueWatching();
  const movies = useMovies();
  const shows = useShows();
  const mv = useMusicVideoArtists();
  const video = useMemo(() => (cont.data ?? []).filter((c) => c.kind !== "album"), [cont.data]);

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {video.length > 0 ? (
        <Rail title="Keep Watching">
          {video.map((it) => (
            <ContinueWatchingCard
              key={`${it.kind}-${it.id}`}
              title={it.title}
              subtitle={it.subtitle}
              artPath={it.poster_path}
              positionSec={it.position_sec}
              durationSec={it.duration_sec}
              width={200}
              onPress={() => router.push(`/watch/${it.media_file_id}`)}
            />
          ))}
        </Rail>
      ) : null}
      <Rail title="New Movies" onSeeAll={() => select("movies")}>
        {newest(movies.data).map((m) => (
          <PosterCard
            key={m.id}
            title={m.title}
            meta={m.year ? String(m.year) : undefined}
            artPath={m.poster_path}
            width={RAIL_POSTER}
            compact
            onPress={() => router.push(`/movies/movie/${m.id}`)}
          />
        ))}
      </Rail>
      <Rail title="New Shows" onSeeAll={() => select("shows")}>
        {newest(shows.data).map((s) => (
          <PosterCard
            key={s.id}
            title={s.title}
            meta={s.year ? String(s.year) : undefined}
            artPath={s.poster_path}
            width={RAIL_POSTER}
            compact
            onPress={() => router.push(`/movies/show/${s.id}`)}
          />
        ))}
      </Rail>
      <Rail title="Video Artists" onSeeAll={() => select("videos")}>
        {(mv.data ?? []).slice(0, 20).map((a) => (
          <Tile
            key={a.id}
            title={a.name}
            subtitle={`${a.video_count} videos`}
            artPath={a.image_path}
            size={RAIL_POSTER}
            compact
            showSubtitle
            onPress={() => router.push(`/movies/mv-artist/${a.id}`)}
          />
        ))}
      </Rail>
    </ScrollView>
  );
}

/** Movies & Shows tab: web-style BROWSE chips (All / Movies / TV Shows / Music
 * Videos) with the PWA's page titles (THE CINEMA, TELEVISION, MUSIC VIDEOS). */
export default function MoviesHome(): React.ReactElement {
  return (
    <HubScreen
      header={<MarqueeHeader />}
      storageKey="hub:video"
      sections={[
        { key: "all", label: "All", title: "Movies & Shows", render: (select) => <VideoAll select={select} /> },
        { key: "movies", label: "Movies", title: "Movies", render: () => <MoviesLibrary /> },
        { key: "shows", label: "TV Shows", title: "Television", render: () => <ShowsLibrary /> },
        { key: "videos", label: "Music Videos", title: "Music Videos", render: () => <MusicVideosLibrary /> },
      ]}
    />
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 140 },
});
