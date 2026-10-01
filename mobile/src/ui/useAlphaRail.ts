import { useMemo, useRef } from "react";
import { FlatList } from "react-native";

import { buildAlphaIndex } from "./alpha";

/** Wire an A-Z rail to a RefreshableGrid: compute the active letters + the row
 * index of each letter's first item, and expose a listRef + onSelect that jumps
 * there. Library lists come back alphabetically sorted from the API, so row
 * index maps directly to the alpha bucket. */
export function useAlphaRail<T>(
  data: T[],
  getTitle: (item: T) => string,
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
    listRef.current?.scrollToIndex({ index: idx, viewPosition: 0, animated: true });
  };
  return { listRef, active: index.letters, onSelect };
}
