import { useLocalSearchParams } from "expo-router";
import { Ellipsis, Shuffle } from "lucide-react-native";
import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View, RefreshControl } from "react-native";

import { useAlbum } from "@/api/queries";
import type { SongRow } from "@/api/types";
import { useDownloads } from "@/download/DownloadProvider";
import { songEntries } from "@/download/entries";
import { usePlayer } from "@/player/PlayerProvider";
import { colors, fonts, MIN_TOUCH, spacing, typography } from "@/state/theme";
import { AlbumTileMenu } from "@/ui/AlbumTileMenu";
import { Artwork } from "@/ui/Artwork";
import { Icon } from "@/ui/Icon";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";
import { TrackRow } from "@/ui/TrackRow";

function shuffled<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor((i * 2654435761) % (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export default function AlbumDetailScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const album = useAlbum(id ?? "");
  const { playSongs, playNext, addToQueue, nowPlaying } = usePlayer();
  const { enqueueMany } = useDownloads();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <Screen title="Album">
      <QueryState
        isLoading={album.isLoading}
        isError={album.isError}
        data={album.data}
        onRetry={album.refetch}
      >
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
            <ScrollView
              refreshControl={
                <RefreshControl refreshing={album.isFetching} onRefresh={album.refetch} tintColor={colors.accent} />
              }
            >
              <View style={styles.header}>
                <Artwork path={detail.cover_path} size={140} rounded />
                <Text style={styles.title}>{detail.title}</Text>
                <Text style={styles.sub}>{detail.artist_name}</Text>
                <View style={styles.actions}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Shuffle album"
                    onPress={() => playSongs(shuffled(songs), 0)}
                    style={({ pressed }) => [styles.shuffleBtn, pressed && styles.pressed]}
                  >
                    <Icon icon={Shuffle} size={18} color={colors.background} />
                    <Text style={styles.shuffleText}>Shuffle</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Album options"
                    onPress={() => setMenuOpen(true)}
                    style={styles.kebab}
                  >
                    <Icon icon={Ellipsis} size={22} color={colors.text} />
                  </Pressable>
                </View>
              </View>
              {songs.map((s, i) => (
                <TrackRow
                  key={s.id}
                  title={s.title}
                  subtitle={s.artist_name}
                  artPath={s.cover_path}
                  active={nowPlaying?.mediaFileId === s.media_files[0]?.id}
                  onPress={() => playSongs(songs, i)}
                  menu={{ song: s, playSongs, playNext, addToQueue }}
                />
              ))}
              <AlbumTileMenu
                visible={menuOpen}
                title={detail.title}
                onPlayNow={() => playSongs(songs, 0)}
                onPlayNext={() => void playNext(songs)}
                onAddToQueue={() => void addToQueue(songs)}
                onShuffle={() => playSongs(shuffled(songs), 0)}
                onDownload={() => enqueueMany(songEntries(songs, detail.title))}
                onClose={() => setMenuOpen(false)}
              />
            </ScrollView>
          );
        }}
      </QueryState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.lg },
  title: { ...typography.heading, textAlign: "center" },
  sub: { ...typography.body, color: colors.textMuted },
  actions: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.md },
  shuffleBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: 999,
    backgroundColor: colors.accent,
  },
  shuffleText: { fontFamily: fonts.uiSemiBold, color: colors.background, fontSize: 15 },
  pressed: { opacity: 0.8 },
  kebab: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
});
