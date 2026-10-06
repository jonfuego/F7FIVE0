import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiClient } from "@/api/client";
import { useApi } from "@/state/auth";
import { getSetting, setSetting } from "@/state/settings";
import { isViewKey, resolveViewPref, shouldPushLocal } from "./viewPrefsLogic";

/** Saved library views (hub tab, sort/filter, genre), stored on the server per
 * user so a view follows the person across phone, web and TV. The phone keeps
 * a local copy under the same settings key it used before views moved to the
 * server, so a screen opens on the right view at once and works offline. */

type ServerPrefs = Record<string, unknown>;

let server: ServerPrefs | null = null;
let loading: Promise<ServerPrefs> | null = null;
const listeners = new Set<() => void>();

function loadServer(api: ApiClient): Promise<ServerPrefs> {
  if (server) return Promise.resolve(server);
  if (!loading) {
    loading = api
      .json<{ prefs: ServerPrefs }>("/api/view-prefs")
      .then((r) => r?.prefs ?? {})
      .catch(() => ({}) as ServerPrefs)
      .then((p) => {
        server = { ...p, ...(server ?? {}) };
        loading = null;
        listeners.forEach((l) => l());
        return server;
      });
  }
  return loading;
}

function pushServer(api: ApiClient, key: string, value: unknown): void {
  if (!isViewKey(key)) return;
  void api
    .json(`/api/view-prefs/${encodeURIComponent(key)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ value }),
    })
    .catch(() => {
      // Best-effort: the local copy keeps the view on this phone.
    });
}

/** [value, setValue] for one saved view. `fallback` is used until a saved
 * value is known; `isValid` drops stored values the screen can't use. */
export function useViewPref<T>(
  key: string,
  fallback: T,
  isValid?: (v: unknown) => v is T,
): [T, (v: T) => void] {
  const api = useApi();
  const fallbackRef = useRef(fallback);
  const validRef = useRef(isValid);
  const [local, setLocalState] = useState<unknown>(undefined);
  const [, bump] = useState(0);

  useEffect(() => {
    let active = true;
    const onChange = () => active && bump((n) => n + 1);
    listeners.add(onChange);
    void getSetting<unknown>(key, undefined).then((v) => {
      if (!active) return;
      setLocalState(v);
      void loadServer(api).then((s) => {
        if (active && shouldPushLocal(s[key], v)) {
          server = { ...(server ?? {}), [key]: v };
          pushServer(api, key, v);
        }
        onChange();
      });
    });
    return () => {
      active = false;
      listeners.delete(onChange);
    };
  }, [api, key]);

  const value = resolveViewPref<T>(server?.[key], local, fallbackRef.current, validRef.current);

  const set = useCallback(
    (v: T) => {
      server = { ...(server ?? {}), [key]: v };
      setLocalState(v);
      void setSetting(key, v);
      listeners.forEach((l) => l());
      pushServer(api, key, v);
    },
    [api, key],
  );

  return [value, set];
}
