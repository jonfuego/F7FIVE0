import { Link } from "expo-router";
import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, spacing, typography } from "@/state/theme";

export default function NotFound(): React.ReactElement {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>Not found</Text>
      <Link href="/" style={styles.link}>
        Go home
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background, gap: spacing.md },
  title: { ...typography.heading },
  link: { ...typography.body, color: colors.accent },
});
