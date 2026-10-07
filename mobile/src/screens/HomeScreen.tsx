import { useRouter } from "expo-router";
import React from "react";
import { ScrollView, StyleSheet, Text, View, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAlbums, useContinueWatching, useOnDeck, useRecent } from "@/api/queries";
import type { AlbumDetail, RecentItem } from "@/api/types";
import { albumToSongs } from "@/player/albumPlay";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, fonts, spacing, typography } from "@/state/theme";
import { ContinueWatchingCard } from "@/ui/ContinueWatchingCard";
import { MarqueeHeader } from "@/ui/MarqueeHeader";
import { PosterCard } from "@/ui/PosterCard";
import { QueryState } from "@/ui/QueryState";

function recentHref(it: RecentItem): string {
  if (it.kind === "movie") return `/movies/movie/${it.id}`;
  if (it.kind === "series") return `/movies/show/${it.id}`;
  if (it.kind === "album") return `/music/album/${it.id}`;
  return it.media_file_id ? `/watch/${it.media_file_id}` : `/movies/movie/${it.id}`;
}

export default function HomeScreen(): React.ReactElement {
  const router = useRouter();
  const api = useApi();
  const { playSongs } = usePlayer();
  // Tile Play: fetch the album detail and start it in the player, the same
  // way the album screen does. The card press still opens the detail screen.
  const playAlbumById = async (albumId: string) => {
    try {
      const detail = await api.json<AlbumDetail>(`/api/albums/${albumId}`);
      const songs = albumToSongs(detail);
      if (songs.length > 0) await playSongs(songs, 0);
    } catch {
      // Best-effort; nothing to play if the detail fetch fails.
    }
  };
  const cont = useContinueWatching();
  const recent = useRecent();
  const albums = useAlbums();
  // On Deck (Plex): the next episode for every started series, rolled forward
  // past finished episodes by GET /api/on-deck (crit 38).
  const deck = useOnDeck();
  const onDeck = deck.data ?? [];
  const refreshing = cont.isFetching || recent.isFetching || albums.isFetching || deck.isFetching;

  const onRefresh = () => {
    void deck.refetch();
    void cont.refetch();
    void recent.refetch();
    void albums.refetch();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <MarqueeHeader section="Home" />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
      >
        {onDeck.length > 0 ? (
          <>
            <Text style={styles.rail} accessibilityLabel="On Deck">
              On Deck
            </Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
              {onDeck.map((it) => (
                <ContinueWatchingCard
                  key={`ondeck-${it.id}`}
                  title={it.title}
                  subtitle={it.subtitle}
                  artPath={it.poster_path}
                  positionSec={it.position_sec}
                  durationSec={it.duration_sec}
                  width={220}
                  onPress={() => router.push(`/watch/${it.media_file_id}`)}
                />
              ))}
            </ScrollView>
          </>
        ) : null}

        <Text style={styles.rail}>Continue Watching</Text>
        <QueryState
          isLoading={cont.isLoading}
          isError={cont.isError}
          data={cont.data}
          onRetry={cont.refetch}
          isEmpty={(d) => d.length === 0}
          emptyTitle="Nothing in progress"
          emptyMessage="Start something and it'll show up here."
        >
          {(items) => (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
              {items.map((it) => (
                <ContinueWatchingCard
                  key={`${it.kind}-${it.id}`}
                  title={it.title}
                  subtitle={it.subtitle}
                  artPath={it.poster_path}
                  positionSec={it.position_sec}
                  durationSec={it.duration_sec}
                  width={220}
                  onPress={() => router.push(`/watch/${it.media_file_id}`)}
                />
              ))}
            </ScrollView>
          )}
        </QueryState>

        <Text style={styles.rail}>Recent Arrivals</Text>
        <QueryState
          isLoading={recent.isLoading}
          isError={recent.isError}
          data={recent.data}
          onRetry={recent.refetch}
          isEmpty={(d) => d.length === 0}
          emptyTitle="Nothing new"
          emptyMessage="New arrivals will show up here."
        >
          {(items) => (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
              {items.map((it) => (
                <PosterCard
                  key={`${it.kind}-${it.id}`}
                  title={it.title}
                  meta={it.subtitle ?? (it.year ? String(it.year) : undefined)}
                  artPath={it.poster_path}
                  width={110}
                  square={it.kind === "album"}
                  round={it.kind === "album"}
                  onPress={() => router.push(recentHref(it) as never)}
                />
              ))}
            </ScrollView>
          )}
        </QueryState>

        <Text style={styles.rail}>Albums</Text>
        <QueryState
          isLoading={albums.isLoading}
          isError={albums.isError}
          data={albums.data}
          onRetry={albums.refetch}
          isEmpty={(d) => d.length === 0}
          emptyTitle="No albums yet"
          emptyMessage="Your music library will appear here."
        >
          {(items) => (
            <View style={styles.grid}>
              {items.slice(0, 12).map((al) => (
                <PosterCard
                  key={al.id}
                  title={al.title}
                  meta={al.artist_name}
                  artPath={al.cover_path}
                  width={110}
                  square
                  round
                  onPress={() => router.push(`/music/album/${al.id}`)}
                  onPlay={() => void playAlbumById(al.id)}
                />
              ))}
            </View>
          )}
        </QueryState>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.lg, paddingBottom: 140 },
  rail: {
    ...typography.heading,
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: 1,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  row: { gap: spacing.md, paddingRight: spacing.lg },
  grid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", gap: spacing.md },
});
