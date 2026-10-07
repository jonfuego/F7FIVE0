import type { SongRow } from "@/api/types";

import { createTrackRowMenuActions, type TrackRowMenuDeps } from "../trackRowMenuActions";

function song(id: string): SongRow {
  return {
    id,
    title: `Track ${id}`,
    album_id: "al1",
    album_title: "Album One",
    artist_id: "ar1",
    artist_name: "Artist One",
    media_files: [{ id: `mf-${id}` }],
  };
}

function makeDeps(overrides: Partial<TrackRowMenuDeps> = {}): {
  deps: TrackRowMenuDeps;
  playSongs: jest.Mock;
  playNext: jest.Mock;
  addToQueue: jest.Mock;
} {
  const playSongs = jest.fn();
  const playNext = jest.fn();
  const addToQueue = jest.fn();
  const deps: TrackRowMenuDeps = {
    song: song("1"),
    playSongs,
    playNext,
    addToQueue,
    ...overrides,
  };
  return { deps, playSongs, playNext, addToQueue };
}

describe("track row menu actions", () => {
  it("Play now starts just this track at index 0", () => {
    const { deps, playSongs } = makeDeps();
    createTrackRowMenuActions(deps).playNow();
    expect(playSongs).toHaveBeenCalledTimes(1);
    expect(playSongs).toHaveBeenCalledWith([deps.song], 0);
  });

  it("Play next queues just this track after the current one", () => {
    const { deps, playNext, playSongs, addToQueue } = makeDeps();
    createTrackRowMenuActions(deps).playNext();
    expect(playNext).toHaveBeenCalledTimes(1);
    expect(playNext).toHaveBeenCalledWith([deps.song]);
    // Play next must not restart playback or append.
    expect(playSongs).not.toHaveBeenCalled();
    expect(addToQueue).not.toHaveBeenCalled();
  });

  it("Add to queue appends just this track", () => {
    const { deps, addToQueue } = makeDeps();
    createTrackRowMenuActions(deps).addToQueue();
    expect(addToQueue).toHaveBeenCalledTimes(1);
    expect(addToQueue).toHaveBeenCalledWith([deps.song]);
  });

  it("each action acts only on its own row's track", () => {
    const { deps, playNext } = makeDeps({ song: song("7") });
    createTrackRowMenuActions(deps).playNext();
    expect(playNext.mock.calls[0][0]).toHaveLength(1);
    expect(playNext.mock.calls[0][0][0].id).toBe("7");
  });
});
