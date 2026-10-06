// React hook for a saved library view (see lib/view-prefs.ts for the keys).
//
// Views are stored on the server per user and reached through the library
// BFF, so the browser never holds a token. All views load in one request per
// page load and are shared by every page through a module-level cache; a
// change updates the cache at once (so a page you navigate to next sees it)
// and is written to the server in the background.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPut } from "@/lib/client-api";
import {
  mergeViewPrefs,
  resolveViewPref,
  VIEW_PREFS_PATH,
  viewPrefPath,
  type ViewPrefKey,
  type ViewPrefValue,
} from "@/lib/view-prefs";

type Prefs = ReturnType<typeof mergeViewPrefs>;

let cache: Prefs | null = null;
let loading: Promise<Prefs> | null = null;
const listeners = new Set<() => void>();

function load(): Promise<Prefs> {
  if (cache) return Promise.resolve(cache);
  if (!loading) {
    loading = apiGet<{ prefs: Record<string, unknown> }>(VIEW_PREFS_PATH)
      .then((r) => mergeViewPrefs(r?.prefs))
      .catch(() => mergeViewPrefs({}))
      .then((p) => {
        // A change made while the load was in flight wins.
        cache = cache ? { ...p, ...cache } : p;
        loading = null;
        listeners.forEach((l) => l());
        return cache;
      });
  }
  return loading;
}

/** [value, setValue, loaded]. `value` is the key's default until the saved
 * views arrive; `loaded` says when they have. */
export function useViewPref<K extends ViewPrefKey>(
  key: K,
): [ViewPrefValue<K>, (v: ViewPrefValue<K>) => void, boolean] {
  const read = useCallback((): ViewPrefValue<K> => resolveViewPref(key, cache?.[key]), [key]);
  const [value, setLocal] = useState<ViewPrefValue<K>>(read);
  const [loaded, setLoaded] = useState<boolean>(cache !== null);

  useEffect(() => {
    const onChange = () => {
      setLocal(read());
      setLoaded(true);
    };
    listeners.add(onChange);
    void load().then(onChange);
    return () => {
      listeners.delete(onChange);
    };
  }, [read]);

  const set = useCallback(
    (v: ViewPrefValue<K>) => {
      cache = { ...(cache ?? mergeViewPrefs({})), [key]: v } as Prefs;
      listeners.forEach((l) => l());
      void apiPut(viewPrefPath(key), { value: v }).catch(() => {
        // Best-effort: the view still applies on this page load.
      });
    },
    [key],
  );

  return [value, set, loaded];
}
