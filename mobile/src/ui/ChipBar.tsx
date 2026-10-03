import React, { useEffect, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, fonts, spacing } from "@/state/theme";

export interface ChipOption {
  key: string;
  label: string;
}

interface ChipBarProps {
  /** Mono small-caps label in front of the chips (BROWSE, GENRE, STATUS). */
  label?: string;
  options: ChipOption[];
  value: string | null;
  onChange: (key: string) => void;
  /** Divider under the bar, like the PWA's `.filter-bar`. */
  divider?: boolean;
}

/** The PWA's `.filter-bar` + `.chip` row: a mono label, then pill chips; the
 * selected chip uses the hive tint and text. Scrolls sideways on
 * phones instead of wrapping into five rows like the web does. */
export function ChipBar({ label, options, value, onChange, divider = true }: ChipBarProps): React.ReactElement {
  // Keep the selected chip in view (e.g. a remembered "Mixes" or a genre far
  // down the row would otherwise sit off-screen).
  const scrollRef = useRef<ScrollView>(null);
  const xs = useRef(new Map<string, number>());
  const scrollToSelected = () => {
    const x = value != null ? xs.current.get(value) : undefined;
    if (x != null) scrollRef.current?.scrollTo({ x: Math.max(0, x - 48), animated: true });
  };
  useEffect(scrollToSelected, [value]);
  return (
    <View style={[styles.wrap, divider && styles.divider]}>
      <ScrollView ref={scrollRef} horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {label ? <Text style={styles.lbl}>{label.toUpperCase()}</Text> : null}
        {options.map((o) => {
          const on = o.key === value;
          return (
            <Pressable
              key={o.key}
              onLayout={(e) => {
                xs.current.set(o.key, e.nativeEvent.layout.x);
                if (o.key === value) scrollToSelected();
              }}
              onPress={() => onChange(o.key)}
              hitSlop={4}
              accessibilityRole="button"
              accessibilityLabel={o.label}
              accessibilityState={{ selected: on }}
              style={({ pressed, focused }) => [
                chipStyles.chip,
                on && chipStyles.on,
                focused && chipStyles.focused,
                pressed && !on && chipStyles.pressed,
              ]}
            >
              <Text style={[chipStyles.txt, on && chipStyles.txtOn]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

/** Shared web chip look (also used by SortFilterBar). */
export const chipStyles = StyleSheet.create({
  chip: {
    minHeight: 36,
    paddingHorizontal: 16,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "rgba(34,27,22,0.6)",
    justifyContent: "center",
  },
  on: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
    shadowColor: colors.accent,
    shadowOpacity: 0.35,
    shadowRadius: 9,
    shadowOffset: { width: 0, height: 0 },
    elevation: 4,
  },
  focused: { borderColor: colors.accent, borderWidth: 2 },
  pressed: { backgroundColor: colors.surfaceHi },
  txt: { fontFamily: fonts.uiMedium, fontSize: 13, color: colors.ink2 },
  txtOn: { fontFamily: fonts.uiSemiBold, color: colors.background },
});

const styles = StyleSheet.create({
  wrap: { paddingVertical: spacing.sm },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  row: { alignItems: "center", gap: 8, paddingHorizontal: spacing.lg },
  lbl: {
    fontFamily: fonts.mono,
    fontSize: 10,
    letterSpacing: 2,
    color: colors.textMuted,
    marginRight: 4,
  },
});
