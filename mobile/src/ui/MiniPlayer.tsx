import { useRouter } from "expo-router";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { usePlayer } from "@/player/PlayerProvider";
import { colors, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "./Artwork";
import { IconButton } from "./IconButton";

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
        name={isPlaying ? "pause" : "play"}
        onPress={togglePlay}
        accessibilityLabel={isPlaying ? "Pause" : "Play"}
      />
      <IconButton name="play-skip-forward" onPress={next} accessibilityLabel="Next track" />
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
