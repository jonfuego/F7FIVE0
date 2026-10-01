import React from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "@/state/theme";
import { MarqueeHeader } from "./MarqueeHeader";
import { PageTitle } from "./PageTitle";

interface LibraryScreenProps {
  /** Big Bebas page title (THE CINEMA, TELEVISION, ...). */
  title: string;
  children: React.ReactNode;
}

/** Chrome for a stand-alone library page, matching the PWA: the F7FIVE0
 * marquee, then the page title, then the page body (chips + grid). */
export function LibraryScreen({ title, children }: LibraryScreenProps): React.ReactElement {
  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <MarqueeHeader />
      <PageTitle>{title}</PageTitle>
      <View style={styles.body}>{children}</View>
    </SafeAreaView>
  );
}

/** Body padding shared by library content when embedded in a hub. */
export const libraryBody = StyleSheet.create({
  pad: { flex: 1, paddingHorizontal: spacing.lg },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  body: { flex: 1 },
});
