import AsyncStorage from "@react-native-async-storage/async-storage";
// SDK 54 moved the classic API to expo-file-system/legacy.
import * as FileSystem from "expo-file-system/legacy";
import * as Network from "expo-network";
import { AppState } from "react-native";
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
import { fetchPodcastDownloadUrl, reportPodcastProgress } from "@/api/podcasts";
import type { StreamQuality } from "@/api/types";
import { useApi } from "@/state/auth";
import { getSetting, setSetting, SETTINGS, useSetting } from "@/state/settings";
import {
  addEvent,
  clearPodcastUpTo,
  emptyBuffer,
  flush,
  latestPodcastPosition,
  type BufferedEvent,
  type FlushBuffer,
} from "./flushBuffer";
import { downloadSource } from "./podcastEntries";
import {
  CACHE_MIN_FREE_BYTES,
  cacheBytes,
  cachedPath,
  cacheReduce,
  emptyCache,
  evictable,
  nextCacheToStart,
  restoreCache,
  type CacheEntry,
  type CacheKind,
  type CacheState,
} from "./autoCache";
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
/** Audio saved while it plays (autoCache.ts); not shown as Downloads. */
const CACHE_DIR = (FileSystem.documentDirectory ?? "") + "autocache/";
const CACHE_KEY = "mh:autocache";

/** Something to save while it plays. */
export interface CacheRequest {
  id: string;
  kind: CacheKind;
  title: string;
  meta?: DownloadMeta;
}

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
  /** The latest position of a podcast episode kept while offline, or null. */
  podcastPositionFor: (episodeId: string) => number | null;
  /** Drop a buffered podcast save taken at or before `atMs` (a newer one reached the server). */
  clearBufferedPodcast: (episodeId: string, atMs: number) => void;
  /** Send the offline buffer now if anything is in it (never throws). */
  flushBuffered: () => Promise<void>;
  /** Audio saved while it plays: on/off (on by default), what is saved, and
   * how much space it uses. */
  autoCacheOn: boolean;
  setAutoCacheOn: (on: boolean) => void;
  audioCache: { entries: CacheEntry[]; bytes: number };
  /** Save these while they play (no-op when off). Asking again keeps an entry
   * another 7 days. */
  cacheAudio: (items: CacheRequest[]) => void;
  /** A podcast episode now counts as played: its saved copy can go. */
  markAudioPlayed: (id: string) => void;
  /** What the player has loaded; never removed while it is. */
  setAudioInUse: (ids: string[]) => void;
  /** Called when a save finishes, so the player can switch to the file. */
  onAudioCached: (listener: (id: string, localPath: string) => void) => () => void;
  /** Remove every saved copy (Downloads are not touched). */
  clearAudioCache: () => Promise<void>;
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
  const [cache, cacheDispatch] = useReducer(cacheReduce, undefined, emptyCache);
  const cacheRef = useRef<CacheState>(cache);
  cacheRef.current = cache;
  const [autoCacheOn, setAutoCacheOnSetting] = useSetting<boolean>(SETTINGS.autoCacheAudio, true);
  const inUse = useRef<Set<string>>(new Set());
  const cacheListeners = useRef<Set<(id: string, localPath: string) => void>>(new Set());
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
      await FileSystem.makeDirectoryAsync(CACHE_DIR, { intermediates: true }).catch(() => {});
      const rawCache = await AsyncStorage.getItem(CACHE_KEY).catch(() => null);
      let savedCache: CacheEntry[] = [];
      if (rawCache) {
        try {
          savedCache = (JSON.parse(rawCache) as CacheState).entries ?? [];
        } catch {
          /* ignore corrupt cache list */
        }
      }
      const cacheExists = new Set<string>();
      for (const e of savedCache) {
        if (e.status === "done" && e.localPath) {
          const info = await FileSystem.getInfoAsync(e.localPath).catch(() => null);
          if (info?.exists) cacheExists.add(e.id);
        }
      }
      cacheDispatch({ type: "hydrate", state: restoreCache(savedCache, (e) => cacheExists.has(e.id)) });
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

  // Sends the buffer. Before, it only ran on an offline->online edge seen by a
  // 10 s JS poll, so a save that failed while the phone counted as online (a
  // token refresh or a dropped request) sat in the buffer, and the next time
  // the network blinked it was sent and moved the server back to that old
  // place. Now it also runs when the app comes to the front and after a live
  // podcast save, each podcast save carries the time it was taken (the server
  // ignores one older than what it has), and a newer save that reached the
  // server clears the buffered one.
  const flushing = useRef(false);
  const doFlush = useCallback(async () => {
    if (flushing.current || bufferRef.current.events.length === 0) return;
    flushing.current = true;
    try {
      const snapshot = bufferRef.current;
      const unsent = await flush(snapshot, async (event) => {
        if (event.kind === "progress") {
          await reportProgress(api, event.mediaFileId, event.positionSec, event.durationSec);
        } else if (event.kind === "podcast_progress") {
          await reportPodcastProgress(api, event.episodeId, event.positionSec, event.durationSec, {
            recordedAtMs: event.at,
            client: "phone-buffer",
          });
        } else {
          await postTrackPlay(api, event.trackId, event.msPlayed, event.completed);
        }
      });
      // Keep what failed, plus anything buffered while this ran.
      let next = unsent;
      for (const e of bufferRef.current.events) {
        if (!snapshot.events.includes(e)) next = addEvent(next, e);
      }
      bufferRef.current = next;
      await AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(next)).catch(() => {});
    } finally {
      flushing.current = false;
    }
  }, [api]);

  // Coming back to the front is a good time to send anything that was kept.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") void doFlush().catch(() => {});
    });
    return () => sub.remove();
  }, [doFlush]);

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
        // A podcast episode downloads from its signed /stream/podcast URL (so it
        // works whether or not the server has the file); everything else from
        // the media file download endpoint.
        signed =
          downloadSource(next.kind) === "podcast"
            ? await fetchPodcastDownloadUrl(api, id)
            : await fetchDownloadUrl(api, id);
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

  // ---- Audio saved while it plays (autoCache.ts) ----------------------------
  useEffect(() => {
    if (!hydrated) return;
    void AsyncStorage.setItem(CACHE_KEY, JSON.stringify(cache)).catch(() => {});
  }, [cache, hydrated]);

  const deleteCached = useCallback(async (entries: CacheEntry[]) => {
    for (const e of entries) {
      if (e.localPath) await FileSystem.deleteAsync(e.localPath, { idempotent: true }).catch(() => {});
      cacheDispatch({ type: "remove", id: e.id });
    }
  }, []);

  const evictNow = useCallback(() => {
    const gone = evictable(cacheRef.current, Date.now(), inUse.current);
    if (gone.length) void deleteCached(gone);
  }, [deleteCached]);

  // Tidy once loaded and each time the app comes to the front.
  useEffect(() => {
    if (!hydrated) return;
    evictNow();
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") evictNow();
    });
    return () => sub.remove();
  }, [hydrated, evictNow]);

  // One save at a time, apart from Downloads so neither waits on the other.
  // Skipped while offline, while off, and while the phone is short of space.
  const cacheRunning = useRef(false);
  useEffect(() => {
    if (!hydrated || !online || !autoCacheOn || cacheRunning.current) return;
    const next = nextCacheToStart(cache);
    if (!next) return;
    cacheRunning.current = true;
    const id = next.id;
    cacheDispatch({ type: "start", id });
    void (async () => {
      let target: string | null = null;
      try {
        const free = await FileSystem.getFreeDiskStorageAsync().catch(() => Number.MAX_SAFE_INTEGER);
        if (free < CACHE_MIN_FREE_BYTES) throw new Error("low_space");
        const signed =
          next.kind === "podcast" ? await fetchPodcastDownloadUrl(api, id) : await fetchDownloadUrl(api, id);
        target = CACHE_DIR + localFileName(encodeURIComponent(id), next.meta?.container ?? signed.container);
        const res = await FileSystem.downloadAsync(signed.url, target);
        if (res.status >= 400) throw new Error(`http_${res.status}`);
        const info = await FileSystem.getInfoAsync(res.uri);
        const bytes = info.exists && "size" in info ? info.size : 0;
        cacheDispatch({ type: "complete", id, localPath: res.uri, bytes });
        for (const l of cacheListeners.current) {
          try {
            l(id, res.uri);
          } catch {
            /* a listener error never stops the cache */
          }
        }
      } catch {
        if (target) await FileSystem.deleteAsync(target, { idempotent: true }).catch(() => {});
        cacheDispatch({ type: "fail", id });
      } finally {
        cacheRunning.current = false;
      }
    })();
    // Only react to the set of entries and their status.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cache.entries.map((e) => `${e.id}:${e.status}`).join(","), api, hydrated, online, autoCacheOn]);

  const cacheAudio = useCallback(
    (items: CacheRequest[]) => {
      if (!autoCacheOn) return;
      const now = Date.now();
      for (const it of items) {
        // Already kept as a download: nothing to save.
        if (stateRef.current.items.some((i) => i.id === it.id && i.status === "done")) continue;
        cacheDispatch({ type: "request", id: it.id, kind: it.kind, title: it.title, meta: it.meta, now });
      }
    },
    [autoCacheOn],
  );

  const markAudioPlayed = useCallback(
    (id: string) => {
      const e = cacheRef.current.entries.find((x) => x.id === id);
      if (!e || e.playedAt !== undefined) return;
      cacheDispatch({ type: "played", id, now: Date.now() });
    },
    [],
  );

  const setAudioInUse = useCallback(
    (ids: string[]) => {
      inUse.current = new Set(ids);
      evictNow();
    },
    [evictNow],
  );

  const onAudioCached = useCallback((listener: (id: string, localPath: string) => void) => {
    cacheListeners.current.add(listener);
    return () => {
      cacheListeners.current.delete(listener);
    };
  }, []);

  const clearAudioCache = useCallback(async () => {
    const all = cacheRef.current.entries.filter((e) => e.status !== "downloading" && !inUse.current.has(e.id));
    await deleteCached(all);
  }, [deleteCached]);

  const setAutoCacheOn = useCallback(
    (on: boolean) => {
      setAutoCacheOnSetting(on);
    },
    [setAutoCacheOnSetting],
  );

  const enqueue = useCallback((mediaFileId: string, title: string, opts?: EnqueueOptions): boolean => {
    if (!canEnqueue(stateRef.current)) return false;
    // Already saved while it played: keep that file instead of fetching it again.
    const saved = cacheRef.current.entries.find((e) => e.id === mediaFileId && e.status === "done");
    if (saved?.localPath && !stateRef.current.items.some((i) => i.id === mediaFileId)) {
      const from = saved.localPath;
      const to = DL_DIR + from.slice(from.lastIndexOf("/") + 1);
      void (async () => {
        try {
          await FileSystem.moveAsync({ from, to });
          cacheDispatch({ type: "remove", id: mediaFileId });
          dispatch({ type: "enqueue", id: mediaFileId, title, kind: opts?.kind, meta: opts?.meta });
          dispatch({ type: "complete", id: mediaFileId, localPath: to, bytes: saved.bytes });
        } catch {
          dispatch({ type: "enqueue", id: mediaFileId, title, kind: opts?.kind, meta: opts?.meta });
        }
      })();
      return true;
    }
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

  /** A file on the phone to play: a download, else a copy saved while it played. */
  const localPathFor = useCallback(
    (mediaFileId: string) =>
      stateRef.current.items.find((i) => i.id === mediaFileId && i.status === "done")?.localPath ??
      cachedPath(cacheRef.current, mediaFileId),
    [],
  );

  const bufferOffline = useCallback((event: BufferedEvent) => {
    bufferRef.current = addEvent(bufferRef.current, event);
    void AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(bufferRef.current)).catch(() => {});
  }, []);

  const podcastPositionFor = useCallback(
    (episodeId: string) => latestPodcastPosition(bufferRef.current, episodeId),
    [],
  );

  const clearBufferedPodcast = useCallback((episodeId: string, atMs: number) => {
    const next = clearPodcastUpTo(bufferRef.current, episodeId, atMs);
    if (next === bufferRef.current) return;
    bufferRef.current = next;
    void AsyncStorage.setItem(BUFFER_KEY, JSON.stringify(next)).catch(() => {});
  }, []);

  const flushBuffered = useCallback(() => doFlush().catch(() => {}), [doFlush]);

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
      podcastPositionFor,
      clearBufferedPodcast,
      flushBuffered,
      autoCacheOn,
      setAutoCacheOn,
      audioCache: { entries: cache.entries, bytes: cacheBytes(cache) },
      cacheAudio,
      markAudioPlayed,
      setAudioInUse,
      onAudioCached,
      clearAudioCache,
    }),
    [
      state, online, enqueue, enqueueMany, itemFor, cancel, retry, remove, setLimitMb, isDownloaded, localPathFor,
      bufferOffline, podcastPositionFor, clearBufferedPodcast, flushBuffered, autoCacheOn, setAutoCacheOn, cache,
      cacheAudio, markAudioPlayed, setAudioInUse, onAudioCached, clearAudioCache,
    ],
  );

  return <DownloadContext.Provider value={value}>{children}</DownloadContext.Provider>;
}

export function useDownloads(): DownloadContextValue {
  const ctx = useContext(DownloadContext);
  if (!ctx) throw new Error("useDownloads must be used within DownloadProvider");
  return ctx;
}
