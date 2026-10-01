import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useAlbum } from "@/api/queries";
import type { SongRow } from "@/api/types";
import { usePlayer } from "@/player/PlayerProvider";
import { colors, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";
import { TrackRow } from "@/ui/TrackRow";

/** TV album detail: large art, a "Play album" button that takes initial D-pad
 * focus (Select plays), and a focusable track list. */
export default function TvDetail(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const album = useAlbum(id ?? "");
  const { playSongs } = usePlayer();
  const router = useRouter();

  return (
    <Screen title="Details">
      <QueryState isLoading={album.isLoading} isError={album.isError} data={album.data} onRetry={album.refetch}>
        {(detail) => {
          const songs: SongRow[] = detail.tracks.map((t) => ({
            id: t.id,
            title: t.title,
            track_number: t.track_number,
            disc_number: t.disc_number,
            duration_sec: t.duration_sec,
            album_id: detail.id,
            album_title: detail.title,
            cover_path: detail.cover_path,
            artist_id: detail.artist_id,
            artist_name: detail.artist_name ?? "",
            media_files: t.media_files,
          }));
          return (
            <ScrollView>
              <View style={styles.header}>
                <Artwork path={detail.cover_path} size={220} rounded />
                <View style={styles.meta}>
                  <Text style={styles.title}>{detail.title}</Text>
                  <Text style={styles.sub}>{detail.artist_name}</Text>
                  <Pressable
                    hasTVPreferredFocus
                    onPress={() => playSongs(songs, 0)}
                    accessibilityRole="button"
                    accessibilityLabel="Play album"
                    style={({ focused }) => [styles.play, focused && styles.playFocused]}
                  >
                    {({ focused }) => (
                      <Text style={[styles.playTxt, focused && { color: colors.background }]}>Play album</Text>
                    )}
                  </Pressable>
                </View>
              </View>
              {songs.map((s, i) => (
                <TrackRow key={s.id} title={s.title} subtitle={s.artist_name} artPath={s.cover_path} onPress={() => playSongs(songs, i)} />
              ))}
            </ScrollView>
          );
        }}
      </QueryState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  play: {
    alignSelf: "flex-start",
    marginTop: spacing.md,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: 999,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 2,
    borderColor: "transparent",
  },
  playFocused: { backgroundColor: colors.bulb, borderColor: colors.bulb, transform: [{ scale: 1.06 }] },
  playTxt: { ...typography.heading, color: colors.text },
  header: { flexDirection: "row", gap: spacing.xl, paddingVertical: spacing.xl, alignItems: "center" },
  meta: { flex: 1, gap: spacing.sm },
  title: { ...typography.title },
  sub: { ...typography.body, color: colors.textMuted },
});
