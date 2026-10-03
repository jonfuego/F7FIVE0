import { Check, Film, Music } from "lucide-react-native";
import React, { useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { resolveArtUri } from "@/api/media";
import { useApi } from "@/state/auth";
import { colors, fonts, radius, spacing } from "@/state/theme";
import { Icon } from "./Icon";
import { tvFocusStyle } from "./tvFocus";

interface PosterCardProps {
  title: string;
  meta?: string | null;
  artPath?: string | null;
  /** Card width in dp. Height is derived from the aspect ratio. */
  width: number;
  /** true for albums/artists (1:1), false for posters (2:3). */
  square?: boolean;
  round?: boolean;
  watched?: boolean;
  /** 0..1 resume fraction. Renders the thin bottom progress bar when > 0. */
  progress?: number;
  onPress: () => void;
  /** Dense grids: title only, smaller type (meta stays in the a11y label). */
  compact?: boolean;
}

/** Derive a stable warm hue from the title so the placeholder isn't a flat box
 * (matches the PWA MediaCard --pg / --ph tinting idea). */
function tintFor(title: string): string {
  let h = 0;
  for (let i = 0; i < title.length; i += 1) h = (h * 31 + title.charCodeAt(i)) % 360;
  return `hsl(${h}, 22%, 16%)`;
}

/** Library poster/cover card, ported from frontend/components/MediaCard.tsx:
 * 2:3 poster (or 1:1 for albums/artists), tinted placeholder, title + meta
 * line, a watched check, and a thin resume progress bar. Focusable for TV. */
export function PosterCard({
  title,
  meta,
  artPath,
  width,
  square,
  round,
  watched,
  progress = 0,
  onPress,
  compact,
}: PosterCardProps): React.ReactElement {
  const api = useApi();
  const uri = resolveArtUri(artPath);
  const [failed, setFailed] = useState(false);
  const height = square ? width : Math.round(width * 1.5);
  const isServerArt = !!artPath && !/^https?:\/\//i.test(artPath);
  const headers = isServerArt ? api.authHeaders() : undefined;
  const frame = {
    width,
    height,
    borderRadius: round ? radius.md : radius.sm,
    backgroundColor: tintFor(title),
  };
  const pct = Math.max(0, Math.min(1, progress));

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={meta ? `${title}, ${meta}` : title}
      style={({ pressed, focused }) => [
        styles.card,
        { width },
        tvFocusStyle(focused),
        pressed && styles.pressed,
      ]}
    >
      <View style={[styles.frame, frame]}>
        {uri && !failed ? (
          <Image
            source={{ uri, headers }}
            onError={() => setFailed(true)}
            style={[styles.art, frame]}
            resizeMode="cover"
            accessibilityIgnoresInvertColors
          />
        ) : (
          <View style={[styles.placeholder, frame]}>
            <Icon
              icon={square ? Music : Film}
              size={Math.round(width * 0.28)}
              color={colors.textFaint}
            />
          </View>
        )}
        {watched ? (
          <View style={[styles.check, compact && styles.checkCompact]}>
            <Icon icon={Check} size={compact ? 11 : 13} color={colors.background} />
          </View>
        ) : null}
        {pct > 0 ? (
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${pct * 100}%` }]} />
          </View>
        ) : null}
      </View>
      <Text style={[styles.title, compact && styles.titleCompact]} numberOfLines={1}>
        {title}
      </Text>
      {meta && !compact ? (
        <Text style={styles.meta} numberOfLines={1}>
          {meta}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { marginBottom: spacing.md },
  frame: { overflow: "hidden" },
  art: { position: "absolute", left: 0, top: 0 },
  placeholder: { alignItems: "center", justifyContent: "center" },
  pressed: { opacity: 0.75 },
  check: {
    position: "absolute",
    top: 8,
    right: 8,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  checkCompact: { top: 4, right: 4, width: 18, height: 18, borderRadius: 9 },
  progressTrack: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: 3,
    backgroundColor: "rgba(0,0,0,0.5)",
  },
  progressFill: { height: 3, backgroundColor: colors.accent },
  title: { fontFamily: fonts.uiSemiBold, fontSize: 14, color: colors.text, marginTop: spacing.xs },
  meta: { fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint, marginTop: 1 },
  titleCompact: { fontSize: 12 },
});
