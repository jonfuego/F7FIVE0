// Audio queue store. Holds the ordered list of QueueItems plus the
// current-playing index and repeat mode. Persisted server-side per user
// at /api/library/queue so the queue follows the user across devices.
// localStorage stays as a write-through cache so the player keeps
// working offline. The MiniPlayer is the only consumer that touches an
// <audio> element; this file is pure state.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import type { AlbumDetail, MediaFile, SongRow, Track } from "./types";

const STORAGE_KEY = "f7five0.queue.v1";
const QUEUE_API = "/api/library/queue";
// The PUT debounce window. Long enough to collapse a flurry of skip /
// add-to-queue clicks into one network write. Short enough that walking
// to a second device sees fresh state after a couple of seconds.
const WRITE_DEBOUNCE_MS = 1500;

export type QueueItem = {
  media_file_id: string;
  title: string;
  artist_name: string | null;
  album_title: string | null;
  cover_path: string | null;
  duration_sec: number | null;
  // Optional: present on items minted via trackToQueueItem and on items
  // returned by /api/library/auto-playlist/*. Used by MiniPlayer to log
  // a row in track_plays. Older items rehydrated from localStorage may
  // not carry it; the play-log write is skipped in that case.
  track_id?: string;
  // Optional: present on items minted in the client where we have the
  // parent IDs in scope. Used to render artist/album text as deep links
  // in the dock and queue panel. Items rehydrated from older
  // localStorage payloads or returned by the auto-playlist server may
  // not carry these; the UI falls back to plain text when null.
  artist_id?: string | null;
  album_id?: string | null;
};

export type RepeatMode = "off" | "all" | "one";

export type PlayAlbumOpts = { shuffle?: boolean };

type State = {
  items: QueueItem[];
  currentIndex: number | null;
  repeat: RepeatMode;
  shuffle: boolean;
  // Whether audio was actively playing when the state was last persisted.
  // Used on fresh page load to decide whether to auto-play the restored
  // track. Stored in localStorage only (not synced to the server queue).
  playing: boolean;
};

const INITIAL_STATE: State = {
  items: [],
  currentIndex: null,
  repeat: "off",
  shuffle: false,
  playing: false,
};

type Action =
  | { type: "hydrate"; state: State }
  | { type: "playAlbum"; items: QueueItem[]; shuffle: boolean }
  | { type: "playNow"; item: QueueItem }
  | { type: "playNext"; item: QueueItem }
  | { type: "playNextBlock"; items: QueueItem[] }
  | { type: "addToQueue"; items: QueueItem[] }
  | { type: "next" }
  | { type: "prev" }
  | { type: "skipTo"; index: number }
  | { type: "removeAt"; index: number }
  | { type: "reorder"; from: number; to: number }
  | { type: "clear" }
  | { type: "setRepeat"; repeat: RepeatMode }
  | { type: "setShuffle"; shuffle: boolean }
  | { type: "setPlaying"; playing: boolean };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "hydrate":
      return action.state;

    case "playAlbum": {
      if (action.items.length === 0) return state;
      const ordered = action.shuffle ? shuffleArray(action.items) : action.items.slice();
      // Set shuffle to match how the album was started. A plain "Play
      // album" forces shuffle off; "Shuffle album" forces it on. Without
      // this the persisted shuffle flag leaks across album plays, so a
      // sequential play would advance randomly.
      return { ...state, items: ordered, currentIndex: 0, shuffle: action.shuffle };
    }

    case "playNow": {
      if (state.items.length === 0 || state.currentIndex === null) {
        return { ...state, items: [action.item], currentIndex: 0 };
      }
      const items = state.items.slice();
      items.splice(state.currentIndex + 1, 0, action.item);
      return { ...state, items, currentIndex: state.currentIndex + 1 };
    }

    case "playNext": {
      if (state.items.length === 0 || state.currentIndex === null) {
        return { ...state, items: [action.item], currentIndex: 0 };
      }
      const items = state.items.slice();
      items.splice(state.currentIndex + 1, 0, action.item);
      return { ...state, items };
    }

    case "playNextBlock": {
      if (action.items.length === 0) return state;
      if (state.items.length === 0 || state.currentIndex === null) {
        return { ...state, items: action.items.slice(), currentIndex: 0 };
      }
      const items = state.items.slice();
      items.splice(state.currentIndex + 1, 0, ...action.items);
      return { ...state, items };
    }

    case "addToQueue": {
      if (action.items.length === 0) return state;
      const items = [...state.items, ...action.items];
      if (state.currentIndex === null) {
        return { ...state, items, currentIndex: 0 };
      }
      return { ...state, items };
    }

    case "next": {
      if (state.currentIndex === null) return state;
      // repeat=one is honored by the MiniPlayer's `ended` handler (seek
      // to 0 and replay). Calling next() explicitly (skip button) still
      // advances, otherwise the user could never get off a track.
      if (state.shuffle && state.items.length > 0) {
        const pool: number[] = [];
        for (let i = 0; i < state.items.length; i++) {
          if (i !== state.currentIndex) pool.push(i);
        }
        if (pool.length === 0) {
          if (state.repeat === "all") return { ...state, currentIndex: 0 };
          return { ...state, currentIndex: null };
        }
        const pick = pool[Math.floor(Math.random() * pool.length)];
        return { ...state, currentIndex: pick };
      }
      const nextIdx = state.currentIndex + 1;
      if (nextIdx >= state.items.length) {
        if (state.repeat === "all" && state.items.length > 0) {
          return { ...state, currentIndex: 0 };
        }
        return { ...state, currentIndex: null };
      }
      return { ...state, currentIndex: nextIdx };
    }

    case "prev": {
      if (state.currentIndex === null) return state;
      if (state.currentIndex === 0) return state;
      return { ...state, currentIndex: state.currentIndex - 1 };
    }

    case "skipTo": {
      if (action.index < 0 || action.index >= state.items.length) return state;
      return { ...state, currentIndex: action.index };
    }

    case "removeAt": {
      if (action.index < 0 || action.index >= state.items.length) return state;
      const items = state.items.slice();
      items.splice(action.index, 1);
      let currentIndex = state.currentIndex;
      if (currentIndex !== null) {
        if (items.length === 0) {
          currentIndex = null;
        } else if (action.index < currentIndex) {
          currentIndex = currentIndex - 1;
        } else if (action.index === currentIndex) {
          if (currentIndex >= items.length) currentIndex = items.length - 1;
        }
      }
      return { ...state, items, currentIndex };
    }

    case "reorder": {
      const { from, to } = action;
      if (from === to) return state;
      const n = state.items.length;
      if (from < 0 || from >= n || to < 0 || to >= n) return state;
      const items = state.items.slice();
      const [moved] = items.splice(from, 1);
      items.splice(to, 0, moved);
      // Keep currentIndex pointing at the same logical track. If the
      // dragged row IS the current track, currentIndex follows it to its
      // new position. Otherwise we shift currentIndex to reflect the
      // surrounding items moving up or down past it.
      let currentIndex = state.currentIndex;
      if (currentIndex !== null) {
        if (currentIndex === from) {
          currentIndex = to;
        } else if (from < currentIndex && to >= currentIndex) {
          currentIndex = currentIndex - 1;
        } else if (from > currentIndex && to <= currentIndex) {
          currentIndex = currentIndex + 1;
        }
      }
      return { ...state, items, currentIndex };
    }

    case "clear":
      return { ...state, items: [], currentIndex: null, playing: false };

    case "setRepeat":
      return { ...state, repeat: action.repeat };

    case "setShuffle":
      return { ...state, shuffle: action.shuffle };

    case "setPlaying":
      return { ...state, playing: action.playing };
  }
}

function shuffleArray<T>(arr: T[]): T[] {
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = out[i];
    out[i] = out[j];
    out[j] = tmp;
  }
  return out;
}

export function trackToQueueItem(track: Track, album: AlbumDetail): QueueItem | null {
  const file = track.media_files[0];
  if (!file) return null;
  return {
    media_file_id: file.id,
    title: track.title,
    artist_name: album.artist_name,
    album_title: album.title,
    cover_path: album.cover_path,
    duration_sec: track.duration_sec,
    track_id: track.id,
    artist_id: album.artist_id ?? null,
    album_id: album.id,
  };
}

export function albumToQueueItems(album: AlbumDetail): QueueItem[] {
  const out: QueueItem[] = [];
  for (const t of album.tracks) {
    const qi = trackToQueueItem(t, album);
    if (qi) out.push(qi);
  }
  return out;
}

export function songRowToQueueItem(row: SongRow): QueueItem | null {
  const file: MediaFile | undefined = row.media_files[0];
  if (!file) return null;
  return {
    media_file_id: file.id,
    title: row.title,
    artist_name: row.artist_name,
    album_title: row.album_title,
    cover_path: row.cover_path,
    duration_sec: row.duration_sec,
    track_id: row.id,
    artist_id: row.artist_id,
    album_id: row.album_id,
  };
}

type ContextValue = State & {
  // True once the initial hydrate (server queue, or localStorage
  // fallback) has resolved. Consumers that mutate the queue based on the
  // current route (e.g. the watch page reconciling an audio file into the
  // dock) gate on this so they don't act against an empty pre-hydration
  // queue and double-insert when the real queue arrives.
  hydrated: boolean;
  playAlbum: (items: QueueItem[], opts?: PlayAlbumOpts) => void;
  playNow: (item: QueueItem) => void;
  playNext: (item: QueueItem) => void;
  playNextBlock: (items: QueueItem[]) => void;
  addToQueue: (items: QueueItem[]) => void;
  next: () => void;
  prev: () => void;
  skipTo: (index: number) => void;
  removeAt: (index: number) => void;
  reorder: (from: number, to: number) => void;
  clear: () => void;
  setRepeat: (r: RepeatMode) => void;
  setShuffle: (s: boolean) => void;
  setPlaying: (p: boolean) => void;
};

const QueueContext = createContext<ContextValue | null>(null);

export function useQueue(): ContextValue {
  const ctx = useContext(QueueContext);
  if (!ctx) throw new Error("useQueue must be used inside <QueueProvider>");
  return ctx;
}

type ServerQueue = {
  items: QueueItem[];
  current_index: number | null;
  repeat_mode: RepeatMode;
  shuffle?: boolean;
  last_writer_id: string | null;
  updated_at: string;
};

function coerceRepeat(v: unknown): RepeatMode {
  if (v === "all") return "all";
  if (v === "one") return "one";
  return "off";
}

function readLocal(): State | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<State> | null;
    if (!parsed || typeof parsed !== "object") return null;
    const items = Array.isArray(parsed.items) ? (parsed.items as QueueItem[]) : [];
    const ci =
      parsed.currentIndex === null || typeof parsed.currentIndex === "number"
        ? (parsed.currentIndex ?? null)
        : null;
    const repeat = coerceRepeat(parsed.repeat);
    const shuffle = parsed.shuffle === true;
    const clamped = ci !== null && ci >= 0 && ci < items.length ? ci : null;
    const playing = parsed.playing === true;
    return { items, currentIndex: clamped, repeat, shuffle, playing };
  } catch {
    return null;
  }
}

function writeLocal(state: State): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        items: state.items,
        currentIndex: state.currentIndex,
        repeat: state.repeat,
        shuffle: state.shuffle,
        playing: state.playing,
      }),
    );
  } catch {
    // localStorage unavailable: ignore.
  }
}

function serverToState(s: ServerQueue): State {
  const items = Array.isArray(s.items) ? s.items : [];
  const ci =
    typeof s.current_index === "number" && s.current_index >= 0 && s.current_index < items.length
      ? s.current_index
      : null;
  const repeat = coerceRepeat(s.repeat_mode);
  const shuffle = s.shuffle === true;
  // `playing` is device-local and not stored server-side. Default to false
  // so loading a queue from the server never auto-plays on its own.
  return { items, currentIndex: ci, repeat, shuffle, playing: false };
}

export function QueueProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const [hydrated, setHydrated] = useState(false);

  // Stable per-tab id used so we can ignore echoes of our own writes
  // when polling the server on visibility change.
  const writerId = useMemo(
    () =>
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2) + Date.now().toString(36),
    [],
  );

  // Tracks the most recent updated_at this tab has either written or
  // hydrated from. Used by the visibility re-fetch to decide whether the
  // server's copy is genuinely newer than what we have locally.
  const lastSyncedAtRef = useRef<number>(0);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestStateRef = useRef<State>(state);
  latestStateRef.current = state;

  // Hydrate on mount: try the server first, fall back to localStorage if
  // the call fails (offline) or the server has nothing for this user.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(QUEUE_API, { cache: "no-store", credentials: "same-origin" });
        if (!cancelled && res.ok) {
          const data = (await res.json()) as ServerQueue;
          const t = Date.parse(data.updated_at);
          if (Number.isFinite(t)) lastSyncedAtRef.current = t;
          if (
            Array.isArray(data.items) &&
            data.items.length > 0 &&
            data.last_writer_id !== writerId
          ) {
            dispatch({ type: "hydrate", state: serverToState(data) });
            setHydrated(true);
            return;
          }
        }
      } catch {
        // Network/parse failure: fall through to localStorage.
      }
      if (!cancelled) {
        const local = readLocal();
        if (local) dispatch({ type: "hydrate", state: local });
        setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [writerId]);

  // Write-through to localStorage on every change. Server PUT is debounced
  // separately below.
  useEffect(() => {
    if (!hydrated) return;
    writeLocal(state);
  }, [state, hydrated]);

  // Debounced PUT to the server. Skipped while we're still hydrating so
  // we don't echo the initial empty state back over a freshly-loaded
  // server queue.
  useEffect(() => {
    if (!hydrated) return;
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      const snap = latestStateRef.current;
      void fetch(QUEUE_API, {
        method: "PUT",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          items: snap.items,
          current_index: snap.currentIndex,
          repeat_mode: snap.repeat,
          shuffle: snap.shuffle,
          last_writer_id: writerId,
        }),
      })
        .then((res) => {
          if (!res.ok) {
            console.warn("queue: PUT failed", res.status);
            return;
          }
          return res.json().then((data: ServerQueue) => {
            const t = Date.parse(data.updated_at);
            if (Number.isFinite(t)) lastSyncedAtRef.current = t;
          });
        })
        .catch((err) => {
          console.warn("queue: PUT error", err);
        });
    }, WRITE_DEBOUNCE_MS);
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [state, hydrated, writerId]);

  // When the tab becomes visible (e.g. switching from laptop to phone),
  // re-fetch the queue. If the server's copy was written by a different
  // tab and is newer than what we've synced, hydrate from it.
  useEffect(() => {
    if (!hydrated) return;
    if (typeof document === "undefined") return;
    const onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      void (async () => {
        try {
          const res = await fetch(QUEUE_API, { cache: "no-store", credentials: "same-origin" });
          if (!res.ok) return;
          const data = (await res.json()) as ServerQueue;
          const t = Date.parse(data.updated_at);
          if (
            Array.isArray(data.items) &&
            data.last_writer_id !== writerId &&
            Number.isFinite(t) &&
            t > lastSyncedAtRef.current
          ) {
            dispatch({ type: "hydrate", state: serverToState(data) });
            lastSyncedAtRef.current = t;
          }
        } catch {
          // Offline / transient network error: ignore.
        }
      })();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [hydrated, writerId]);

  const playAlbum = useCallback((items: QueueItem[], opts?: PlayAlbumOpts) => {
    dispatch({ type: "playAlbum", items, shuffle: !!opts?.shuffle });
  }, []);
  const playNow = useCallback((item: QueueItem) => {
    dispatch({ type: "playNow", item });
  }, []);
  const playNext = useCallback((item: QueueItem) => {
    dispatch({ type: "playNext", item });
  }, []);
  const playNextBlock = useCallback((items: QueueItem[]) => {
    dispatch({ type: "playNextBlock", items });
  }, []);
  const addToQueue = useCallback((items: QueueItem[]) => {
    dispatch({ type: "addToQueue", items });
  }, []);
  const next = useCallback(() => {
    dispatch({ type: "next" });
  }, []);
  const prev = useCallback(() => {
    dispatch({ type: "prev" });
  }, []);
  const skipTo = useCallback((index: number) => {
    dispatch({ type: "skipTo", index });
  }, []);
  const removeAt = useCallback((index: number) => {
    dispatch({ type: "removeAt", index });
  }, []);
  const reorder = useCallback((from: number, to: number) => {
    dispatch({ type: "reorder", from, to });
  }, []);
  const clear = useCallback(() => {
    dispatch({ type: "clear" });
  }, []);
  const setRepeat = useCallback((repeat: RepeatMode) => {
    dispatch({ type: "setRepeat", repeat });
  }, []);
  const setShuffle = useCallback((shuffle: boolean) => {
    dispatch({ type: "setShuffle", shuffle });
  }, []);
  const setPlaying = useCallback((playing: boolean) => {
    dispatch({ type: "setPlaying", playing });
  }, []);

  const value = useMemo<ContextValue>(
    () => ({
      items: state.items,
      currentIndex: state.currentIndex,
      repeat: state.repeat,
      shuffle: state.shuffle,
      playing: state.playing,
      hydrated,
      playAlbum,
      playNow,
      playNext,
      playNextBlock,
      addToQueue,
      next,
      prev,
      skipTo,
      removeAt,
      reorder,
      clear,
      setRepeat,
      setShuffle,
      setPlaying,
    }),
    [
      state,
      hydrated,
      playAlbum,
      playNow,
      playNext,
      playNextBlock,
      addToQueue,
      next,
      prev,
      skipTo,
      removeAt,
      reorder,
      clear,
      setRepeat,
      setShuffle,
      setPlaying,
    ],
  );

  return <QueueContext.Provider value={value}>{children}</QueueContext.Provider>;
}
