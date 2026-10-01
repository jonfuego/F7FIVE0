import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";

interface Props {
  children: React.ReactNode;
  onError?: (error: Error, info: { componentStack: string }) => void;
}

interface State {
  error: Error | null;
}

/** App-wide error boundary. Renders a recoverable fallback and forwards the
 * error to `onError` (wired to POST /api/client/errors in the root). */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }): void {
    this.props.onError?.(error, info);
  }

  reset = () => this.setState({ error: null });

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <View style={styles.wrap}>
          <Text style={styles.title}>Something broke</Text>
          <Text style={styles.body}>The app hit an unexpected error. You can try again.</Text>
          <Pressable
            onPress={this.reset}
            accessibilityRole="button"
            accessibilityLabel="Try again"
            style={styles.btn}
          >
            <Text style={styles.btnText}>Try again</Text>
          </Pressable>
        </View>
      );
    }
    return this.props.children;
  }
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
  title: { ...typography.heading },
  body: { ...typography.body, color: colors.textMuted, textAlign: "center" },
  btn: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
  },
  btnText: { color: "#1a1206", fontWeight: "700" },
});
