import React from "react";
import { StyleSheet, Text } from "react-native";

import { colors, fonts, spacing } from "@/state/theme";

/** Big Bebas section title, ported from the PWA's `.page-title` (THE CINEMA,
 * TELEVISION, MUSIC ...): uppercase display face, tight leading, wide tracking. */
export function PageTitle({ children }: { children: string }): React.ReactElement {
  return (
    <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
      {children.toUpperCase()}
    </Text>
  );
}

const styles = StyleSheet.create({
  title: {
    fontFamily: fonts.display,
    fontSize: 44,
    lineHeight: 46,
    letterSpacing: 1.8,
    color: colors.text,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
  },
});
