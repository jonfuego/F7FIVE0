import React from "react";
import { FlatList, ListRenderItem, RefreshControl, StyleSheet } from "react-native";

import { colors, spacing } from "@/state/theme";

interface RefreshableGridProps<T> {
  data: T[];
  renderItem: ListRenderItem<T>;
  keyExtractor: (item: T, index: number) => string;
  numColumns?: number;
  refreshing: boolean;
  onRefresh: () => void;
  ListHeaderComponent?: React.ComponentProps<typeof FlatList>["ListHeaderComponent"];
  /** Ref to the underlying FlatList (used by the A-Z rail to scroll to a row). */
  listRef?: React.Ref<FlatList<T>>;
}

/** FlatList with pull-to-refresh baked in (usability bar: every list/grid has
 * pull-to-refresh). Exposes the list via `listRef` for A-Z scroll-to-letter. */
export function RefreshableGrid<T>({
  data,
  renderItem,
  keyExtractor,
  numColumns = 1,
  refreshing,
  onRefresh,
  ListHeaderComponent,
  listRef,
}: RefreshableGridProps<T>): React.ReactElement {
  return (
    <FlatList
      ref={listRef}
      key={`cols-${numColumns}`}
      data={data}
      renderItem={renderItem}
      keyExtractor={keyExtractor}
      numColumns={numColumns}
      columnWrapperStyle={numColumns > 1 ? styles.column : undefined}
      contentContainerStyle={styles.content}
      ListHeaderComponent={ListHeaderComponent}
      showsVerticalScrollIndicator={false}
      // A-Z jumps can target a row that hasn't been measured yet: jump to an
      // estimate so the rows around it render, then retry the exact row.
      onScrollToIndexFailed={(info) => {
        const anyRef = listRef as React.MutableRefObject<FlatList<T> | null> | undefined;
        anyRef?.current?.scrollToOffset({ offset: info.averageItemLength * info.index, animated: false });
        setTimeout(() => {
          anyRef?.current?.scrollToIndex({ index: info.index, viewPosition: 0, animated: true });
        }, 120);
      }}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
          colors={[colors.accent]}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 120, paddingTop: spacing.sm },
  // Fixed-width cells (useGrid) packed from the left so a short last row
  // doesn't spread out.
  column: { justifyContent: "flex-start", gap: 10 },
});
