import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";

interface QueryStateProps<T> {
  isLoading: boolean;
  isError: boolean;
  data: T | undefined;
  onRetry?: () => void;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyMessage?: string;
  children: (data: T) => React.ReactNode;
}

/** Shared loading / empty / error+retry wrapper used by every data-driven
 * screen so the three states look and behave identically everywhere
 * (usability bar). */
export function QueryState<T>({
  isLoading,
  isError,
  data,
  onRetry,
  isEmpty,
  emptyTitle = "Nothing here yet",
  emptyMessage = "There's nothing to show on this screen right now.",
  children,
}: QueryStateProps<T>): React.ReactElement {
  if (isLoading && data === undefined) {
    return (
      // Keyed so Android remounts instead of reusing this view for the loaded
      // content (a reused view kept its "Loading" content-description, which
      // TalkBack announced over real content).
      <View key="qs-loading" style={styles.center} accessibilityRole="progressbar" accessibilityLabel="Loading">
        <ActivityIndicator size="large" color={colors.accent} />
        <Text style={styles.muted}>Loading…</Text>
      </View>
    );
  }

  if (isError && data === undefined) {
    return (
      <View key="qs-error" style={styles.center}>
        <Text style={styles.title}>Something went wrong</Text>
        <Text style={styles.muted}>We couldn&apos;t load this. Check your connection and try again.</Text>
        {onRetry ? (
          <Pressable
            onPress={onRetry}
            accessibilityRole="button"
            accessibilityLabel="Retry"
            style={({ pressed }) => [styles.retry, pressed && styles.retryPressed]}
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (data === undefined) {
    return (
      <View key="qs-pending" style={styles.center}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  if (isEmpty && isEmpty(data)) {
    return (
      <View key="qs-empty" style={styles.center}>
        <Text style={styles.title}>{emptyTitle}</Text>
        <Text style={styles.muted}>{emptyMessage}</Text>
        {onRetry ? (
          <Pressable
            onPress={onRetry}
            accessibilityRole="button"
            accessibilityLabel="Refresh"
            style={({ pressed }) => [styles.retry, pressed && styles.retryPressed]}
          >
            <Text style={styles.retryText}>Refresh</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  return <>{children(data)}</>;
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.sm,
    backgroundColor: colors.background,
  },
  title: { ...typography.heading, textAlign: "center" },
  muted: { ...typography.body, color: colors.textMuted, textAlign: "center" },
  retry: {
    marginTop: spacing.md,
    minHeight: MIN_TOUCH,
    minWidth: 120,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
  },
  retryPressed: { backgroundColor: colors.accentPressed },
  retryText: { color: "#1a1206", fontWeight: "700", fontSize: 16 },
});
