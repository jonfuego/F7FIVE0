// Pure queue state for the audio dock: the item shape, the reducer, and the
// initial state. No React and no JSX here, so node:test can import it
// directly (see queue-state.test.ts). lib/queue.tsx wraps it in the
// QueueProvider context.

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

export type State = {
  items: QueueItem[];
  currentIndex: number | null;
  repeat: RepeatMode;
  shuffle: boolean;
  // Whether audio was actively playing when the state was last persisted.
  // Used on fresh page load to decide whether to auto-play the restored
  // track. Stored in localStorage only (not synced to the server queue).
  // Actions that start playback by hand (play an album or a song, pick a
  // queue row, or add to an empty queue) set it, so the first stream after a
  // page load plays when the person asked for it.
  playing: boolean;
};

export const INITIAL_STATE: State = {
  items: [],
  currentIndex: null,
  repeat: "off",
  shuffle: false,
  playing: false,
};

export type Action =
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

export function reducer(state: State, action: Action): State {
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
      return { ...state, items: ordered, currentIndex: 0, shuffle: action.shuffle, playing: true };
    }

    case "playNow": {
      if (state.items.length === 0 || state.currentIndex === null) {
        return { ...state, items: [action.item], currentIndex: 0, playing: true };
      }
      const items = state.items.slice();
      items.splice(state.currentIndex + 1, 0, action.item);
      return { ...state, items, currentIndex: state.currentIndex + 1, playing: true };
    }

    case "playNext": {
      if (state.items.length === 0 || state.currentIndex === null) {
        return { ...state, items: [action.item], currentIndex: 0, playing: true };
      }
      const items = state.items.slice();
      items.splice(state.currentIndex + 1, 0, action.item);
      return { ...state, items };
    }

    case "playNextBlock": {
      if (action.items.length === 0) return state;
      if (state.items.length === 0 || state.currentIndex === null) {
        return { ...state, items: action.items.slice(), currentIndex: 0, playing: true };
      }
      const items = state.items.slice();
      items.splice(state.currentIndex + 1, 0, ...action.items);
      return { ...state, items };
    }

    case "addToQueue": {
      if (action.items.length === 0) return state;
      const items = [...state.items, ...action.items];
      if (state.currentIndex === null) {
        return { ...state, items, currentIndex: 0, playing: true };
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
      return { ...state, currentIndex: action.index, playing: true };
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
