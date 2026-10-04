import { CloudDownload } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { getApiBase } from "@/state/config";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { appUpdateSupported, openServerDownloadPage } from "@/ui/AppUpdate";
import { Icon } from "@/ui/Icon";

/** Shown at launch when the installed build is below the platform's minimum
 * supported version (spec 5.6 / M4 min-version gate). */
export function UpdateRequired(): React.ReactElement {
  return (
    <View style={styles.wrap}>
      <Icon icon={CloudDownload} size={64} color={colors.accent} />
      <Text style={styles.title}>Update required</Text>
      <Text style={styles.body}>
        This version of F7FIVE0 is no longer supported. Please install the latest build to keep
        watching and listening.
      </Text>
      {appUpdateSupported && getApiBase() ? (
        <Pressable
          onPress={() => openServerDownloadPage(getApiBase())}
          accessibilityRole="button"
          accessibilityLabel="Download the update from your server"
          style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
        >
          <Text style={styles.buttonText}>Download from your server</Text>
        </Pressable>
      ) : null}
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
  button: {
    minHeight: MIN_TOUCH + 4,
    paddingHorizontal: spacing.xl,
    marginTop: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonPressed: { backgroundColor: colors.accentPressed },
  buttonText: { color: colors.onHive, fontWeight: "700", fontSize: 16 },
});
