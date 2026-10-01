import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

/** Lightweight persisted settings, backed by AsyncStorage. Used for player
 * preferences (crossfade, gapless, loudness, playback rate) and per-screen sort/
 * filter choices. Only non-sensitive UI state lives here - never tokens. */
const PREFIX = "mh:setting:";

export const SETTINGS = {
  crossfadeSec: "crossfadeSec",
  gapless: "gapless",
  loudness: "loudness",
  loudnessAlbum: "loudnessAlbum",
  loudnessAllowBoost: "loudnessAllowBoost",
  playbackRate: "playbackRate",
  storageLimitMb: "storageLimitMb",
} as const;

export async function getSetting<T>(key: string, fallback: T): Promise<T> {
  try {
    const v = await AsyncStorage.getItem(PREFIX + key);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

export async function setSetting<T>(key: string, value: T): Promise<void> {
  try {
    await AsyncStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // best-effort; settings are non-critical
  }
}

/** React hook for a single persisted setting. Loads async, writes through. */
export function useSetting<T>(key: string, fallback: T): [T, (v: T) => void] {
  const [val, setVal] = useState<T>(fallback);
  useEffect(() => {
    let active = true;
    void getSetting<T>(key, fallback).then((v) => {
      if (active) setVal(v);
    });
    return () => {
      active = false;
    };
    // fallback is a primitive literal per call site; key is the identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const update = useCallback(
    (v: T) => {
      setVal(v);
      void setSetting(key, v);
    },
    [key],
  );
  return [val, update];
}
