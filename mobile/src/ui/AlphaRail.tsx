import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, MIN_TOUCH } from "@/state/theme";
import { alphaBucket, buildAlphaIndex } from "./alpha";

export { alphaBucket, buildAlphaIndex };

const LETTERS = ["#", ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))];

interface AlphaRailProps {
  /** Letters that have at least one item; others render dimmed/disabled. */
  active: Set<string>;
  onSelect: (letter: string) => void;
}

/** Vertical A-Z + # rail pinned to the right edge, ported from
 * frontend/components/AlphaRail.tsx. Disabled letters are dimmed. */
export function AlphaRail({ active, onSelect }: AlphaRailProps): React.ReactElement {
  return (
    <View style={styles.rail} pointerEvents="box-none">
      {LETTERS.map((l) => {
        const enabled = active.has(l);
        return (
          <Pressable
            key={l}
            disabled={!enabled}
            onPress={() => onSelect(l)}
            accessibilityRole="button"
            accessibilityLabel={`Jump to ${l}`}
            hitSlop={6}
            style={styles.hit}
          >
            <Text style={[styles.letter, !enabled && styles.disabled]}>{l}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  rail: {
    position: "absolute",
    right: 2,
    top: 0,
    bottom: 0,
    justifyContent: "center",
    alignItems: "center",
    width: 22,
  },
  hit: { minHeight: Math.floor(MIN_TOUCH / 3), justifyContent: "center" },
  letter: { fontFamily: fonts.mono, fontSize: 10, color: colors.accent, paddingVertical: 1 },
  disabled: { color: colors.textFaint, opacity: 0.4 },
});
