import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "./Artwork";

interface TrackRowProps {
  title: string;
  subtitle?: string | null;
  artPath?: string | null;
  active?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
}

export function TrackRow({ title, subtitle, artPath, active, onPress, onLongPress }: TrackRowProps): React.ReactElement {
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      accessibilityRole="button"
      accessibilityLabel={subtitle ? `${title}, ${subtitle}` : title}
      style={({ pressed, focused }) => [
        styles.row,
        active && styles.active,
        focused && styles.focused,
        pressed && styles.pressed,
      ]}
    >
      <Artwork path={artPath} size={48} rounded />
      <View style={styles.meta}>
        <Text style={[styles.title, active && styles.activeText]} numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.subtitle} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: MIN_TOUCH + 12,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  active: { backgroundColor: colors.surfaceAlt },
  pressed: { opacity: 0.7 },
  focused: { borderWidth: 2, borderColor: colors.accent },
  meta: { flex: 1 },
  title: { ...typography.body },
  activeText: { color: colors.accent, fontWeight: "700" },
  subtitle: { ...typography.caption },
});
