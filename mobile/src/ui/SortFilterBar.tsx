import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, fonts, spacing } from "@/state/theme";
import { chipStyles } from "./ChipBar";
import type { FilterOption, SortDir, SortOption } from "./sortFilter";

interface SortFilterBarProps<T> {
  sorts: SortOption<T>[];
  filters?: FilterOption<T>[];
  sortKey: string;
  dir: SortDir;
  filterKey: string | null;
  onSortKey: (key: string) => void;
  onToggleDir: () => void;
  onFilterKey: (key: string | null) => void;
  /** Mono label before the filter chips (STATUS, SHOW, TYPE). */
  filterLabel?: string;
}

/** Horizontal sort + filter chips for library screens (crit 39). Sort chips pick
 * the sort key; the arrow toggles direction; filter chips (with an "All"
 * pseudo-filter) narrow the list. Web-style 36dp pills (PWA `.chip`) with a
 * 4dp hitSlop so every control still meets the 44dp touch minimum. */
export function SortFilterBar<T>({
  sorts,
  filters,
  sortKey,
  dir,
  filterKey,
  onSortKey,
  onToggleDir,
  onFilterKey,
  filterLabel,
}: SortFilterBarProps<T>): React.ReactElement {
  const filterChips =
    filters && filters.length > 0 ? (
      <>
        <Text style={styles.lbl}>{(filterLabel ?? "Show").toUpperCase()}</Text>
        <Pressable
          hitSlop={4}
          accessibilityRole="button"
          accessibilityLabel="Filter all"
          accessibilityState={{ selected: filterKey == null }}
          onPress={() => onFilterKey(null)}
          style={[chipStyles.chip, filterKey == null && chipStyles.on]}
        >
          <Text style={[chipStyles.txt, filterKey == null && chipStyles.txtOn]}>All</Text>
        </Pressable>
        {filters.map((f) => {
          const on = f.key === filterKey;
          return (
            <Pressable
              key={f.key}
              hitSlop={4}
              accessibilityRole="button"
              accessibilityLabel={`Filter ${f.label}`}
              accessibilityState={{ selected: on }}
              onPress={() => onFilterKey(on ? null : f.key)}
              style={[chipStyles.chip, on && chipStyles.on]}
            >
              <Text style={[chipStyles.txt, on && chipStyles.txtOn]}>{f.label}</Text>
            </Pressable>
          );
        })}
        <View style={styles.sep} />
      </>
    ) : null;

  return (
    <View style={styles.wrap}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {filterChips}
        <Text style={styles.lbl}>SORT</Text>
        {sorts.map((s) => {
          const on = s.key === sortKey;
          return (
            <Pressable
              key={s.key}
              hitSlop={4}
              accessibilityRole="button"
              accessibilityLabel={`Sort by ${s.label}`}
              accessibilityState={{ selected: on }}
              onPress={() => onSortKey(s.key)}
              style={[chipStyles.chip, on && chipStyles.on]}
            >
              <Text style={[chipStyles.txt, on && chipStyles.txtOn]}>{s.label}</Text>
            </Pressable>
          );
        })}
        <Pressable
          hitSlop={4}
          accessibilityRole="button"
          accessibilityLabel={dir === "asc" ? "Sort direction ascending" : "Sort direction descending"}
          onPress={onToggleDir}
          style={styles.dirBtn}
        >
          <Ionicons name={dir === "asc" ? "arrow-up" : "arrow-down"} size={16} color={colors.ink2} />
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  row: { gap: 8, alignItems: "center", paddingRight: spacing.lg },
  lbl: { fontFamily: fonts.mono, fontSize: 10, letterSpacing: 2, color: colors.textMuted, marginRight: 2 },
  dirBtn: {
    width: 36,
    height: 36,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
  },
  sep: { width: 1, height: 22, backgroundColor: colors.line, marginHorizontal: 4 },
});
