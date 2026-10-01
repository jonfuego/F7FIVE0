import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing, typography } from "@/state/theme";

interface ScreenProps {
  title?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  /** Set false for screens that manage their own full-bleed layout. */
  padded?: boolean;
}

/** Standard screen chrome: safe-area insets (notch + gesture bar), dark
 * background, optional title header. */
export function Screen({ title, right, children, padded = true }: ScreenProps): React.ReactElement {
  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      {title ? (
        <View style={styles.header}>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          {right ? <View>{right}</View> : null}
        </View>
      ) : null}
      <View style={[styles.body, padded && styles.padded]}>{children}</View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  title: { ...typography.title, flexShrink: 1 },
  body: { flex: 1 },
  padded: { paddingHorizontal: spacing.lg },
});
