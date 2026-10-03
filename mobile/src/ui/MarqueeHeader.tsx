import { Search } from "lucide-react-native";
import { useRouter } from "expo-router";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, MIN_TOUCH, spacing } from "@/state/theme";
import { HiveWordmark } from "./HiveWordmark";
import { Icon } from "./Icon";

interface MarqueeHeaderProps {
  /** Optional section label shown under the wordmark in the mono meta face. */
  section?: string;
  /** Show the search affordance (tab root screens). Defaults on. */
  search?: boolean;
}

/** The theatre marquee header, ported from frontend/components/MarqueeTop.tsx:
 * the F7FIVE0 wordmark on the left, a search action on the right, over the
 * canonical dark background. Used on the tab root screens. */
export function MarqueeHeader({ section, search = true }: MarqueeHeaderProps): React.ReactElement {
  const router = useRouter();
  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <HiveWordmark />
        {search ? (
          <Pressable
            onPress={() => router.push("/(tabs)/search")}
            accessibilityRole="button"
            accessibilityLabel="Search"
            style={({ pressed }) => [styles.searchBtn, pressed && styles.pressed]}
          >
            <Icon icon={Search} size={20} color={colors.textMuted} />
          </Pressable>
        ) : null}
      </View>
      {section ? <Text style={styles.section}>{section.toUpperCase()}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  searchBtn: {
    minWidth: MIN_TOUCH,
    minHeight: MIN_TOUCH,
    alignItems: "center",
    justifyContent: "center",
  },
  pressed: { opacity: 0.6 },
  section: {
    fontFamily: fonts.mono,
    fontSize: 11,
    letterSpacing: 2,
    color: colors.textFaint,
    marginTop: spacing.xs,
  },
});
