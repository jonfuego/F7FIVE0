import { useRouter } from "expo-router";
import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAlbums, useContinueWatching, useMovies, useOnDeck, useRecent, useShows } from "@/api/queries";
import type { RecentItem } from "@/api/types";
import { colors, fonts, spacing } from "@/state/theme";
import { ContinueWatchingCard } from "@/ui/ContinueWatchingCard";
import { MarqueeHeader } from "@/ui/MarqueeHeader";
import { QueryState } from "@/ui/QueryState";
import { Tile } from "@/ui/Tile";

function recentHref(it: RecentItem): string {
  if (it.kind === "movie") return `/movies/movie/${it.id}`;
  if (it.kind === "series") return `/movies/show/${it.id}`;
  if (it.kind === "album") return `/music/album/${it.id}`;
  return it.media_file_id ? `/watch/${it.media_file_id}` : `/movies/movie/${it.id}`;
}

/** 10-foot browse for Android TV (spec F): the marquee header over large,
 * D-pad-focusable rails (On Deck, Continue Watching, Recently Added, Movies,
 * Shows, Albums). Every tile has a visible focus style (Tile /
 * ContinueWatchingCard). Movies and shows open their detail screens (movie
 * detail, show with seasons); albums open the TV album detail. No requests or
 * admin surfaces on TV. */
export default function TvBrowse(): React.ReactElement {
  const router = useRouter();
  const deck = useOnDeck();
  const cont = useContinueWatching();
  const recent = useRecent();
  const movies = useMovies();
  const shows = useShows();
  const albums = useAlbums();

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <MarqueeHeader section="Home" />
      <ScrollView contentContainerStyle={styles.content}>
        {(deck.data ?? []).length > 0 ? (
          <>
            <Text style={styles.rail}>On Deck</Text>
            <ScrollView horizontal contentContainerStyle={styles.row}>
              {(deck.data ?? []).map((it, i) => (
                <ContinueWatchingCard
                  key={`deck-${it.id}`}
                  title={it.title}
                  subtitle={it.subtitle}
                  artPath={it.poster_path}
                  positionSec={it.position_sec}
                  durationSec={it.duration_sec}
                  width={320}
                  hasTVPreferredFocus={i === 0}
                  onPress={() => router.push(`/watch/${it.media_file_id}`)}
                />
              ))}
            </ScrollView>
          </>
        ) : null}

        <Text style={styles.rail}>Continue Watching</Text>
        <QueryState isLoading={cont.isLoading} isError={cont.isError} data={cont.data} onRetry={cont.refetch} isEmpty={(d) => d.length === 0} emptyTitle="Nothing in progress">
          {(items) => (
            <ScrollView horizontal contentContainerStyle={styles.row}>
              {items.map((it, i) => (
                <ContinueWatchingCard
                  key={`cw-${it.kind}-${it.id}`}
                  title={it.title}
                  subtitle={it.subtitle}
                  artPath={it.poster_path}
                  positionSec={it.position_sec}
                  durationSec={it.duration_sec}
                  width={320}
                  hasTVPreferredFocus={(deck.data ?? []).length === 0 && i === 0}
                  onPress={() => router.push(`/watch/${it.media_file_id}`)}
                />
              ))}
            </ScrollView>
          )}
        </QueryState>

        <Text style={styles.rail}>Recently Added</Text>
        <QueryState isLoading={recent.isLoading} isError={recent.isError} data={recent.data} onRetry={recent.refetch} isEmpty={(d) => d.length === 0}>
          {(items) => (
            <ScrollView horizontal contentContainerStyle={styles.row}>
              {items.map((it) => (
                <Tile key={`r-${it.kind}-${it.id}`} title={it.title} subtitle={it.subtitle} artPath={it.poster_path} size={180} onPress={() => router.push(recentHref(it))} />
              ))}
            </ScrollView>
          )}
        </QueryState>

        <Text style={styles.rail}>Movies</Text>
        <QueryState isLoading={movies.isLoading} isError={movies.isError} data={movies.data} onRetry={movies.refetch} isEmpty={(d) => d.length === 0}>
          {(items) => (
            <ScrollView horizontal contentContainerStyle={styles.row}>
              {items.slice(0, 30).map((m) => (
                <Tile key={m.id} title={m.title} subtitle={m.year ? String(m.year) : undefined} artPath={m.poster_path} size={180} onPress={() => router.push(`/movies/movie/${m.id}`)} />
              ))}
            </ScrollView>
          )}
        </QueryState>

        <Text style={styles.rail}>Shows</Text>
        <QueryState isLoading={shows.isLoading} isError={shows.isError} data={shows.data} onRetry={shows.refetch} isEmpty={(d) => d.length === 0}>
          {(items) => (
            <ScrollView horizontal contentContainerStyle={styles.row}>
              {items.slice(0, 30).map((s) => (
                <Tile key={s.id} title={s.title} subtitle={s.year ? String(s.year) : undefined} artPath={s.poster_path} size={180} onPress={() => router.push(`/movies/show/${s.id}`)} />
              ))}
            </ScrollView>
          )}
        </QueryState>

        <Text style={styles.rail}>Albums</Text>
        <QueryState isLoading={albums.isLoading} isError={albums.isError} data={albums.data} onRetry={albums.refetch} isEmpty={(d) => d.length === 0}>
          {(items) => (
            <ScrollView horizontal contentContainerStyle={styles.row}>
              {items.slice(0, 30).map((a) => (
                <Tile key={a.id} title={a.title} subtitle={a.artist_name} artPath={a.cover_path} size={180} onPress={() => router.push(`/music/album/${a.id}`)} />
              ))}
            </ScrollView>
          )}
        </QueryState>
        <View style={{ height: spacing.xxl }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.xxl, paddingBottom: spacing.xxl },
  rail: {
    fontFamily: fonts.display,
    fontSize: 32,
    letterSpacing: 1,
    color: colors.text,
    marginTop: spacing.xl,
    marginBottom: spacing.md,
  },
  row: { gap: spacing.lg, paddingRight: spacing.xl, paddingVertical: spacing.sm },
});
