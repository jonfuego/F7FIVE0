import AsyncStorage from "@react-native-async-storage/async-storage";
// SDK 54 moved the classic API to expo-file-system/legacy.
import * as FileSystem from "expo-file-system/legacy";
import * as Network from "expo-network";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import { fetchDownloadUrl, postTrackPlay, reportProgress } from "@/api/media";
import type { StreamQuality } from "@/api/types";
import { useApi } from "@/state/auth";
import { getSetting, setSetting, SETTINGS } from "@/state/settings";
import {
  addEvent,
  emptyBuffer,
  flush,
  type BufferedEvent,
  type FlushBuffer,
} from "./flushBuffer";
import {
  canEnqueue,
  initialState,
  retryDownload,
  localFileName,
  nextToStart,
  reduce,
  restoreItems,
  usedBytes,
  type DownloadItem,
  type DownloadKind,
  type DownloadMeta,
  type DownloadState,
} from "./queue";

const META_KEY = "mh:downloads:meta";
const BUFFER_KEY = "mh:downloads:buffer";
/** Files live under this dir, named by media_file_id (never a URL). */
const DL_DIR = (FileSystem.documentDirectory ?? "") + "downloads/";

export interface EnqueueOptions {
  kind?: DownloadKind;
  meta?: DownloadMeta;
  quality?: StreamQuality;
}

interface DownloadContextValue {
  state: DownloadState;
  usedBytes: number;
  online: boolean;
  /** Queue one media file. Returns false when the storage limit blocks it. */
  enqueue: (mediaFileId: string, title: string, opts?: EnqueueOptions) => boolean;
  /** Queue several (an album, a mix, a season). Returns how many were queued. */
  enqueueMany: (entries: { mediaFileId: string; title: string; opts?: EnqueueOptions }[]) => number;
  /** A finished download's record (kind/meta/localPath), if any. */
  itemFor: (mediaFileId: string) => DownloadItem | undefined;
  cancel: (mediaFileId: string) => void;
  /** Queue a failed download again. Returns false when it isn't failed (or the
   * storage limit blocks it). */
  retry: (mediaFileId: string) => boolean;
  remove: (mediaFileId: string) => Promise<void>;
  setLimitMb: (mb: number) => void;
  isDownloaded: (mediaFileId: string) => boolean;
  localPathFor: (mediaFileId: string) => string | undefined;
  /** Buffer a progress/track-play while offline; flushed on reconnect. */
  bufferOffline: (event: BufferedEvent) => void;
}

const DownloadContext = createContext<DownloadContextValue | null>(null);

function fileUriFor(mediaFileId: string, container?: string | null): string {
  return DL_DIR + localFileName(encodeURIComponent(mediaFileId), container);
}

export function DownloadProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const api = useApi();
  const [state, dispatch] = useReducer(reduce, undefined, () => initialState(0));
  const [online, setOnline] = useState(true);
  const bufferRef = useRef<FlushBuffer>(emptyBuffer());
  const tasks = useRef<Map<string, { task: FileSystem.DownloadResumable; target: string }>>(new Map());
  const stateRef = useRef(state);
  stateRef.current = state;
  // Persisting before hydration finishes would overwrite the saved list with
  // the empty initial state on every launch, so writes wait for this flag.
  const [hydrated, setHydrated] = useState(false);

  // Hydrate persisted metadata, storage limit and the offline buffer on launch.
  useEffect(() => {
    void (async () => {
      await FileSystem.makeDirectoryAsync(DL_DIR, { intermediates: true }).catch(() => {});
      const limitMb = await getSetting<number>(SETTINGS.storageLimitMb, 0);
      const limitBytes = Math.max(0, limitMb) * 1024 * 1024;
      const rawMeta = await AsyncStorage.getItem(META_KEY).catch(() => null);
      let saved: DownloadItem[] = [];
      if (rawMeta) {
        try {
          saved = (JSON.parse(rawMeta) as DownloadState).items ?? [];
        } catch {
          /* ignore corrupt meta */
        }
      }
      // Keep only finished files that are still on disk; re-queue in-flight ones.
      const exists = new Set<string>();
      for (const it of saved) {
        if (it.status === "done" && it.localPath) {
          const info = await FileSystem.getInfoAsync(it.localPath).catch(() => null);
          if (info?.exists) exists.add(it.id);
        }
      }
      dispatch({ type: "hydrate", state: restoreItems(saved, (it) => exists.has(it.id), limitBytes) });
      const rawBuf = await AsyncStorage.getItem(BUFFER_KEY).catch(() => null);
      if (rawBuf) {
        try {
          bufferRef.current = JSON.parse(rawBuf) as FlushBuffer;
        } catch {
          /* ignore */
        }
      }
      setHydrated(true);
    })();
  }, []);

  // Persist metadata whenever state changes (only after hydration).
  useEffect(() => {
    if (!hydrated) return;
    void AsyncStorage.setItem(META_KEY, JSON.stringify(state)).catch(() => {});
  }, [state, hydrated]);

  // Poll network state; flush the offline buffer on the offline->online edge.
  useEffect(() => {
    let mounted = true;
    const check = async () => {
      const st = await Network.getNetworkStateAsync().catch(() => null);
      const isOnline = !!st?.isConnected && st.isInternetReachable !== false;
      if (!mounted) return;
      setOnline((prev) => {
        if (!prev && isOnline) void doFlush();
        return isOnline;
      });
    };
    void check();
    const timer = setInterval(check, 10_000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
    // doFlush is stable via useCallback below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doFlush = useCallback(async () => {
    const next = await flush(bufferRef.current, async (event) => {
      if (event.kind === "progress") {
        await reportProgress(api, event.mediaFileId, event.positionSec, event.durationSec);
      } else {
        await postTrackPlay(api, event.trackId, event.msPlayed, event.completed);
      }
    });
    bufferRef.current = next;
    await AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(next)).catch(() => {});
  }, [api]);

  // Drive the queue: whenever state changes and nothing is downloading, start the
  // next queued item.
  useEffect(() => {
    if (!hydrated || !online) return;
    const next = nextToStart(state);
    if (!next) return;
    const id = next.id;
    dispatch({ type: "start", id });
    void (async () => {
      // Mint a signed URL (bearer-authenticated call, so the access token is
      // refreshed if needed); the file transfer itself carries no bearer that
      // could expire mid-download. 409 = video that can't be offered offline.
      let signed: { url: string; container?: string | null };
      try {
        signed = await fetchDownloadUrl(api, id);
      } catch (e) {
        const status = (e as { status?: number }).status;
        dispatch({
          type: "fail",
          id,
          error: status === 409 ? "not_available_offline" : e instanceof Error ? e.message : "download_error",
        });
        return;
      }
      const target = fileUriFor(id, next.meta?.container ?? signed.container);
      const task = FileSystem.createDownloadResumable(signed.url, target, {}, (p) => {
        dispatch({
          type: "progress",
          id,
          bytes: p.totalBytesWritten,
          totalBytes: p.totalBytesExpectedToWrite > 0 ? p.totalBytesExpectedToWrite : undefined,
        });
      });
      tasks.current.set(id, { task, target });
      try {
        const res = await task.downloadAsync();
        tasks.current.delete(id);
        if (!res) {
          // Canceled.
          return;
        }
        if (res.status === 409) {
          await FileSystem.deleteAsync(res.uri, { idempotent: true }).catch(() => {});
          dispatch({ type: "fail", id, error: "not_available_offline" });
          return;
        }
        if (res.status >= 400) {
          await FileSystem.deleteAsync(res.uri, { idempotent: true }).catch(() => {});
          dispatch({ type: "fail", id, error: `http_${res.status}` });
          return;
        }
        const info = await FileSystem.getInfoAsync(res.uri);
        const bytes = info.exists && "size" in info ? info.size : 0;
        dispatch({ type: "complete", id, localPath: res.uri, bytes });
      } catch (e) {
        tasks.current.delete(id);
        dispatch({ type: "fail", id, error: e instanceof Error ? e.message : "download_error" });
      }
    })();
    // Only react to the set of items/statuses, not every progress tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.items.map((i) => `${i.id}:${i.status}`).join(","), api, hydrated, online]);

  const enqueue = useCallback((mediaFileId: string, title: string, opts?: EnqueueOptions): boolean => {
    if (!canEnqueue(stateRef.current)) return false;
    dispatch({ type: "enqueue", id: mediaFileId, title, kind: opts?.kind, meta: opts?.meta });
    return true;
  }, []);

  const enqueueMany = useCallback(
    (entries: { mediaFileId: string; title: string; opts?: EnqueueOptions }[]): number => {
      if (!canEnqueue(stateRef.current)) return 0;
      let n = 0;
      for (const e of entries) {
        dispatch({ type: "enqueue", id: e.mediaFileId, title: e.title, kind: e.opts?.kind, meta: e.opts?.meta });
        n += 1;
      }
      return n;
    },
    [],
  );

  /** Every path a file for this id may live at (in-flight target, finished
   * path, legacy extension-less name). */
  const pathsFor = (mediaFileId: string): string[] => {
    const item = stateRef.current.items.find((i) => i.id === mediaFileId);
    const paths = new Set<string>([fileUriFor(mediaFileId), fileUriFor(mediaFileId, item?.meta?.container)]);
    const t = tasks.current.get(mediaFileId);
    if (t) paths.add(t.target);
    if (item?.localPath) paths.add(item.localPath);
    return [...paths];
  };

  const cancel = useCallback((mediaFileId: string) => {
    const paths = pathsFor(mediaFileId);
    const t = tasks.current.get(mediaFileId);
    if (t) {
      void t.task.cancelAsync().catch(() => {});
      tasks.current.delete(mediaFileId);
    }
    for (const p of paths) void FileSystem.deleteAsync(p, { idempotent: true }).catch(() => {});
    dispatch({ type: "cancel", id: mediaFileId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retry = useCallback((mediaFileId: string): boolean => {
    const cur = stateRef.current;
    if (!canEnqueue(cur)) return false;
    if (retryDownload(cur, mediaFileId) === cur) return false;
    // A failed transfer can leave a partial file; the retry starts clean.
    tasks.current.delete(mediaFileId);
    for (const p of pathsFor(mediaFileId)) void FileSystem.deleteAsync(p, { idempotent: true }).catch(() => {});
    dispatch({ type: "retry", id: mediaFileId });
    return true;
  }, []);

  const remove = useCallback(async (mediaFileId: string) => {
    const paths = pathsFor(mediaFileId);
    const t = tasks.current.get(mediaFileId);
    if (t) {
      await t.task.cancelAsync().catch(() => {});
      tasks.current.delete(mediaFileId);
    }
    for (const p of paths) await FileSystem.deleteAsync(p, { idempotent: true }).catch(() => {});
    dispatch({ type: "remove", id: mediaFileId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const itemFor = useCallback(
    (mediaFileId: string) => stateRef.current.items.find((i) => i.id === mediaFileId && i.status === "done"),
    [],
  );

  const setLimitMb = useCallback((mb: number) => {
    dispatch({ type: "setLimit", bytes: Math.max(0, mb) * 1024 * 1024 });
    void setSetting(SETTINGS.storageLimitMb, Math.max(0, mb));
  }, []);

  const isDownloaded = useCallback(
    (mediaFileId: string) =>
      stateRef.current.items.some((i) => i.id === mediaFileId && i.status === "done"),
    [],
  );

  const localPathFor = useCallback(
    (mediaFileId: string) =>
      stateRef.current.items.find((i) => i.id === mediaFileId && i.status === "done")?.localPath,
    [],
  );

  const bufferOffline = useCallback((event: BufferedEvent) => {
    bufferRef.current = addEvent(bufferRef.current, event);
    void AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(bufferRef.current)).catch(() => {});
  }, []);

  const value = useMemo<DownloadContextValue>(
    () => ({
      state,
      usedBytes: usedBytes(state),
      online,
      enqueue,
      enqueueMany,
      itemFor,
      cancel,
      retry,
      remove,
      setLimitMb,
      isDownloaded,
      localPathFor,
      bufferOffline,
    }),
    [state, online, enqueue, enqueueMany, itemFor, cancel, retry, remove, setLimitMb, isDownloaded, localPathFor, bufferOffline],
  );

  return <DownloadContext.Provider value={value}>{children}</DownloadContext.Provider>;
}

export function useDownloads(): DownloadContextValue {
  const ctx = useContext(DownloadContext);
  if (!ctx) throw new Error("useDownloads must be used within DownloadProvider");
  return ctx;
}
