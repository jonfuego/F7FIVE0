// Pure action factory for a single track row's 3-dot menu (Play now, Play
// next, Add to queue). Kept free of React and react-native-track-player so the
// jest test can drive it with plain spies and pin the behaviour: Play now
// starts the one track, Play next inserts it after the current track without
// interrupting playback, Add to queue appends it. TrackRow wires the real
// player callbacks in; the test wires spies. Mirrors playerMenuActions.ts.

import type { SongRow } from "@/api/types";

export interface TrackRowMenuDeps {
  // The track this row acts on.
  song: SongRow;
  // From usePlayer(): start the given songs at an index.
  playSongs: (songs: SongRow[], startIndex: number) => void | Promise<void>;
  // From usePlayer(): queue the songs directly after the current track.
  playNext: (songs: SongRow[]) => void | Promise<void>;
  // From usePlayer(): append the songs to the end of the queue.
  addToQueue: (songs: SongRow[]) => void | Promise<void>;
}

export interface TrackRowMenuActions {
  playNow: () => void | Promise<void>;
  playNext: () => void | Promise<void>;
  addToQueue: () => void | Promise<void>;
}

export function createTrackRowMenuActions(deps: TrackRowMenuDeps): TrackRowMenuActions {
  return {
    playNow: () => deps.playSongs([deps.song], 0),
    playNext: () => deps.playNext([deps.song]),
    addToQueue: () => deps.addToQueue([deps.song]),
  };
}
