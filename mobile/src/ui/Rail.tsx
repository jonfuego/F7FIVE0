import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, fonts, spacing } from "@/state/theme";

interface RailProps {
  title: string;
  /** "See all" jumps to the full grid (switches the hub chip). */
  onSeeAll?: () => void;
  children: React.ReactNode;
}

/** A titled horizontal shelf for the hub "All" views (Plex/Plexamp-style
 * landing), with a mono "See all" link. */
export function Rail({ title, onSeeAll, children }: RailProps): React.ReactElement {
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title}>{title}</Text>
        {onSeeAll ? (
          <Pressable
            onPress={onSeeAll}
            accessibilityRole="button"
            accessibilityLabel={`See all ${title}`}
            hitSlop={10}
          >
            <Text style={styles.more}>SEE ALL</Text>
          </Pressable>
        ) : null}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {children}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: spacing.lg },
  head: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  title: { fontFamily: fonts.display, fontSize: 24, letterSpacing: 1, color: colors.text },
  more: { fontFamily: fonts.mono, fontSize: 10, letterSpacing: 2, color: colors.textMuted },
  row: { gap: 10, paddingHorizontal: spacing.lg },
});
