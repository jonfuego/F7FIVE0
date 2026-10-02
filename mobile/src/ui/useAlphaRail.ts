import { useMemo, useRef } from "react";
import { FlatList } from "react-native";

import { buildAlphaIndex, rowForItem } from "./alpha";

/** Wire an A-Z rail to a RefreshableGrid: compute the active letters + the
 * index of each letter's first item, and expose a listRef + onSelect that jumps
 * there. A FlatList with numColumns > 1 indexes by ROW, so the item index is
 * divided by the column count before scrolling. */
export function useAlphaRail<T>(
  data: T[],
  getTitle: (item: T) => string,
  numColumns = 1,
): { listRef: React.RefObject<FlatList<T>>; active: Set<string>; onSelect: (letter: string) => void } {
  const listRef = useRef<FlatList<T>>(null);
  const index = useMemo(
    () => buildAlphaIndex(data.map(getTitle)),
    // getTitle is a stable per-screen accessor; key the memo on the data only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data],
  );
  const onSelect = (letter: string): void => {
    const idx = index.firstIndex[letter];
    if (idx == null) return;
    listRef.current?.scrollToIndex({ index: rowForItem(idx, numColumns), viewPosition: 0, animated: true });
  };
  return { listRef, active: index.letters, onSelect };
}
