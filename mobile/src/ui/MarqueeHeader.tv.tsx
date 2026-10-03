import { Search } from "lucide-react-native";
import { useRouter } from "expo-router";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, spacing } from "@/state/theme";
import { HiveWordmark } from "./HiveWordmark";
import { Icon } from "./Icon";

interface MarqueeHeaderProps {
  section?: string;
  search?: boolean;
}

/** TV variant of the marquee header (resolved only in the EXPO_TV build via
 * metro.config.js). Laid out for 10-foot viewing: a larger wordmark, a
 * D-pad-focusable search tile with a visible focus ring, and roomier spacing.
 * Same props as the phone MarqueeHeader so callers don't change. */
export function MarqueeHeader({ section, search = true }: MarqueeHeaderProps): React.ReactElement {
  const router = useRouter();
  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <HiveWordmark height={48} />
        {search ? (
          <Pressable
            onPress={() => router.push("/(tabs)/search")}
            accessibilityRole="button"
            accessibilityLabel="Search"
            style={({ focused, pressed }) => [
              styles.searchTile,
              focused && styles.focused,
              pressed && styles.pressed,
            ]}
          >
            <Icon icon={Search} size={28} color={colors.text} />
            <Text style={styles.searchLabel}>Search</Text>
          </Pressable>
        ) : null}
      </View>
      {section ? <Text style={styles.section}>{section.toUpperCase()}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.xxl,
    paddingTop: spacing.xl,
    paddingBottom: spacing.lg,
  },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  searchTile: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: "transparent",
    backgroundColor: colors.bg2,
  },
  focused: { borderColor: colors.accent, transform: [{ scale: 1.06 }] },
  pressed: { opacity: 0.7 },
  searchLabel: { fontFamily: fonts.uiSemiBold, fontSize: 24, color: colors.text },
  section: {
    fontFamily: fonts.mono,
    fontSize: 24,
    letterSpacing: 3,
    color: colors.textFaint,
    marginTop: spacing.sm,
  },
});
