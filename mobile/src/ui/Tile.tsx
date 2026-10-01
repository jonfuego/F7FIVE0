import React from "react";
import { Pressable, StyleSheet, Text } from "react-native";

import { colors, fonts, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "./Artwork";

interface TileProps {
  title: string;
  subtitle?: string | null;
  artPath?: string | null;
  size: number;
  onPress: () => void;
  round?: boolean;
  /** Dense grids: show the title only (the subtitle stays in the a11y label). */
  compact?: boolean;
  /** Show the subtitle even in compact mode (artist album counts). */
  showSubtitle?: boolean;
}

/** Poster/cover tile used across grids. Focusable with a visible focus style
 * (TV D-pad) and a full accessibilityLabel. */
export function Tile({ title, subtitle, artPath, size, onPress, round, compact, showSubtitle }: TileProps): React.ReactElement {
  const sub = subtitle && (!compact || showSubtitle) ? subtitle : null;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={subtitle ? `${title}, ${subtitle}` : title}
      style={({ pressed, focused }) => [
        styles.tile,
        { width: size },
        focused && styles.focused,
        pressed && styles.pressed,
      ]}
    >
      <Artwork path={artPath} size={size} rounded={round} />
      <Text style={[styles.title, compact && styles.titleCompact]} numberOfLines={1}>
        {title}
      </Text>
      {sub ? (
        <Text style={[styles.subtitle, compact && styles.subtitleCompact]} numberOfLines={1}>
          {sub}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: { marginBottom: spacing.md, borderRadius: radius.md },
  pressed: { opacity: 0.7 },
  focused: {
    transform: [{ scale: 1.06 }],
    borderWidth: 2,
    borderColor: colors.accent,
    borderRadius: radius.md,
  },
  title: { ...typography.label, color: colors.text, marginTop: spacing.xs },
  subtitle: { ...typography.caption },
  titleCompact: { fontFamily: fonts.uiSemiBold, fontSize: 12, fontWeight: "600" },
  subtitleCompact: { fontFamily: fonts.mono, fontSize: 10, color: colors.textFaint },
});
