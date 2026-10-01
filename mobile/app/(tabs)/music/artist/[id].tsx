import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View, RefreshControl } from "react-native";

import { fetchAutoPlaylistById, useArtist } from "@/api/queries";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";
import { Tile } from "@/ui/Tile";

export default function ArtistDetailScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const artist = useArtist(id ?? "");
  const router = useRouter();
  const api = useApi();
  const { playSongs } = usePlayer();
  const [busy, setBusy] = useState<null | "shuffle" | "radio">(null);

  // by-artist = shuffle the artist's own tracks; artist-radio = similar-artist
  // radio. Both are auto-playlist kinds reached via fetchMixSongs' composite id.
  const start = async (kind: "shuffle" | "radio") => {
    setBusy(kind);
    try {
      const apKind = kind === "shuffle" ? "by-artist" : "artist-radio";
      const songs = await fetchAutoPlaylistById(api, apKind, id ?? "");
      if (songs.length > 0) playSongs(songs, 0);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Screen title="Artist">
      <QueryState
        isLoading={artist.isLoading}
        isError={artist.isError}
        data={artist.data}
        onRetry={artist.refetch}
      >
        {(detail) => (
          <ScrollView
            refreshControl={
              <RefreshControl refreshing={artist.isFetching} onRefresh={artist.refetch} tintColor={colors.accent} />
            }
          >
            <View style={styles.header}>
              <Artwork path={detail.image_path} size={140} rounded />
              <Text style={styles.title}>{detail.name}</Text>
              {detail.bio_text ? (
                <Text style={styles.bio} numberOfLines={4}>
                  {detail.bio_text}
                </Text>
              ) : null}
              <View style={styles.actions}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Shuffle artist"
                  disabled={busy !== null}
                  onPress={() => void start("shuffle")}
                  style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
                >
                  <Ionicons name="shuffle" size={18} color={colors.background} />
                  <Text style={styles.primaryText}>{busy === "shuffle" ? "Loading..." : "Shuffle"}</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Start radio"
                  disabled={busy !== null}
                  onPress={() => void start("radio")}
                  style={({ pressed }) => [styles.ghost, pressed && styles.pressed]}
                >
                  <Ionicons name="radio" size={18} color={colors.text} />
                  <Text style={styles.ghostText}>{busy === "radio" ? "Loading..." : "Start radio"}</Text>
                </Pressable>
              </View>
            </View>
            <View style={styles.grid}>
              {detail.albums.map((al) => (
                <Tile
                  key={al.id}
                  title={al.title}
                  subtitle={al.release_date ?? undefined}
                  artPath={al.cover_path}
                  size={108}
                  onPress={() => router.push(`/music/album/${al.id}`)}
                />
              ))}
            </View>
          </ScrollView>
        )}
      </QueryState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.lg },
  title: { ...typography.heading, fontFamily: fonts.display, fontSize: 28, textAlign: "center" },
  bio: { ...typography.caption, textAlign: "center", paddingHorizontal: spacing.lg },
  actions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.md },
  primary: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.bulb,
  },
  primaryText: { fontFamily: fonts.uiSemiBold, color: colors.background, fontSize: 15 },
  ghost: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
  },
  ghostText: { fontFamily: fonts.uiMedium, color: colors.text, fontSize: 15 },
  pressed: { opacity: 0.8 },
  grid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", gap: spacing.md },
});
