import { useRouter } from "expo-router";
import { Pause, Play, SkipForward } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { usePlayer } from "@/player/PlayerProvider";
import { colors, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "./Artwork";
import { IconButton } from "./IconButton";
import { PlayerTrackMenu } from "./PlayerTrackMenu";

/** Persistent mini-player shown above the tab bar whenever something is queued.
 * Tap opens the full now-playing screen. */
export function MiniPlayer(): React.ReactElement | null {
  const { nowPlaying, isPlaying, togglePlay, next, hasQueue } = usePlayer();
  const router = useRouter();

  if (!hasQueue || !nowPlaying) return null;

  return (
    <Pressable
      onPress={() => router.push("/now-playing")}
      accessibilityRole="button"
      accessibilityLabel={`Now playing ${nowPlaying.title}. Open full player.`}
      style={styles.wrap}
    >
      <Artwork path={nowPlaying.artPath} size={44} rounded />
      <View style={styles.meta}>
        <Text style={styles.title} numberOfLines={1}>
          {nowPlaying.title}
        </Text>
        {nowPlaying.artist ? (
          <Text style={styles.artist} numberOfLines={1}>
            {nowPlaying.artist}
          </Text>
        ) : null}
      </View>
      <IconButton
        icon={isPlaying ? Pause : Play}
        onPress={togglePlay}
        accessibilityLabel={isPlaying ? "Pause" : "Play"}
        size={24}
        diameter={48}
        square
        fill
      />
      <IconButton icon={SkipForward} onPress={next} accessibilityLabel="Next track" fill />
      <PlayerTrackMenu
        albumId={nowPlaying.albumId ?? null}
        artistId={nowPlaying.artistId ?? null}
        size={22}
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginHorizontal: spacing.sm,
    marginBottom: spacing.xs,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  meta: { flex: 1 },
  title: { ...typography.label, color: colors.text },
  artist: { ...typography.caption },
});
