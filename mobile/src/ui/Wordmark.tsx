import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, fonts } from "@/state/theme";

/** The F7FIVE0 wordmark, matching frontend/components/Wordmark.tsx: "F7"
 * in the serif face, "FIVE0" in the Bebas display face, tinted
 * with the ivory bulb accent. */
export function Wordmark({ size = 30 }: { size?: number }): React.ReactElement {
  return (
    <View style={styles.row} accessibilityRole="header" accessibilityLabel="F7FIVE0">
      <Text style={[styles.lead, { fontSize: size * 0.72 }]}>F7</Text>
      <Text style={[styles.tail, { fontSize: size }]}>FIVE0</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "baseline" },
  lead: {
    fontFamily: fonts.serifRegular,
    color: colors.textMuted,
    letterSpacing: 0.5,
  },
  tail: {
    fontFamily: fonts.display,
    color: colors.bulb,
    letterSpacing: 2,
    textShadowColor: colors.bulbGlow,
    textShadowRadius: 10,
  },
});
