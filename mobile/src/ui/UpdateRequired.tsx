import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, spacing, typography } from "@/state/theme";

/** Shown at launch when the installed build is below the platform's minimum
 * supported version (spec 5.6 / M4 min-version gate). */
export function UpdateRequired(): React.ReactElement {
  return (
    <View style={styles.wrap}>
      <Ionicons name="cloud-download-outline" size={64} color={colors.accent} />
      <Text style={styles.title}>Update required</Text>
      <Text style={styles.body}>
        This version of F7FIVE0 is no longer supported. Please install the latest build to keep
        watching and listening.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
    backgroundColor: colors.background,
  },
  title: { ...typography.title },
  body: { ...typography.body, color: colors.textMuted, textAlign: "center" },
});
