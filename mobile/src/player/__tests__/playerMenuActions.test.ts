// Mock TrackPlayer so a pause/stop/reset slip in the action logic would show up
// here. The actions must only navigate or queue, never interrupt playback, so
// these spies stay untouched for every action.
const pause = jest.fn();
const stop = jest.fn();
const reset = jest.fn();
jest.mock("react-native-track-player", () => ({
  __esModule: true,
  default: { pause, stop, reset },
}));

import type { SongRow } from "@/api/types";
import {
  albumRoute,
  artistRoute,
  createPlayerMenuActions,
  type PlayerMenuDeps,
} from "../playerMenuActions";

function song(id: string): SongRow {
  return {
    id,
    title: `Track ${id}`,
    album_id: "al1",
    album_title: "Album One",
    artist_id: "ar1",
    artist_name: "Artist One",
    media_files: [],
  };
}

function makeDeps(overrides: Partial<PlayerMenuDeps> = {}): {
  deps: PlayerMenuDeps;
  navigate: jest.Mock;
  closeNowPlaying: jest.Mock;
  playNext: jest.Mock;
  addToQueue: jest.Mock;
} {
  const navigate = jest.fn();
  const closeNowPlaying = jest.fn();
  const playNext = jest.fn();
  const addToQueue = jest.fn();
  const deps: PlayerMenuDeps = {
    albumId: "al1",
    artistId: "ar1",
    navigate,
    closeNowPlaying,
    loadAlbumSongs: async () => [song("1"), song("2")],
    loadArtistRadio: async () => [song("3"), song("4")],
    playNext,
    addToQueue,
    ...overrides,
  };
  return { deps, navigate, closeNowPlaying, playNext, addToQueue };
}

describe("player menu routes", () => {
  it("builds the album and artist detail routes", () => {
    expect(albumRoute("al1")).toBe("/music/album/al1");
    expect(artistRoute("ar1")).toBe("/music/artist/ar1");
  });
});

describe("goToAlbum / goToArtist", () => {
  it("closes Now Playing then navigates to the album route", () => {
    const { deps, navigate, closeNowPlaying } = makeDeps();
    createPlayerMenuActions(deps).goToAlbum();
    expect(closeNowPlaying).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/music/album/al1");
    // Close happens before the push.
    expect(closeNowPlaying.mock.invocationCallOrder[0]).toBeLessThan(
      navigate.mock.invocationCallOrder[0],
    );
  });

  it("closes Now Playing then navigates to the artist route", () => {
    const { deps, navigate, closeNowPlaying } = makeDeps();
    createPlayerMenuActions(deps).goToArtist();
    expect(closeNowPlaying).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/music/artist/ar1");
  });

  it("does nothing when the id is missing", () => {
    const { deps, navigate, closeNowPlaying } = makeDeps({ albumId: null, artistId: null });
    const actions = createPlayerMenuActions(deps);
    actions.goToAlbum();
    actions.goToArtist();
    expect(navigate).not.toHaveBeenCalled();
    expect(closeNowPlaying).not.toHaveBeenCalled();
  });
});

describe("queue actions", () => {
  it("play album next queues the album after the current track", async () => {
    const { deps, playNext } = makeDeps();
    await createPlayerMenuActions(deps).playAlbumNext();
    expect(playNext).toHaveBeenCalledTimes(1);
    expect(playNext.mock.calls[0][0]).toHaveLength(2);
  });

  it("add album to queue appends the album", async () => {
    const { deps, addToQueue } = makeDeps();
    await createPlayerMenuActions(deps).addAlbumToQueue();
    expect(addToQueue).toHaveBeenCalledTimes(1);
  });

  it("artist radio queues the radio after the current track", async () => {
    const { deps, playNext } = makeDeps();
    await createPlayerMenuActions(deps).artistRadio();
    expect(playNext).toHaveBeenCalledTimes(1);
  });

  it("skips queueing when the loader returns nothing", async () => {
    const { deps, playNext, addToQueue } = makeDeps({
      loadAlbumSongs: async () => [],
      loadArtistRadio: async () => [],
    });
    const actions = createPlayerMenuActions(deps);
    await actions.playAlbumNext();
    await actions.addAlbumToQueue();
    await actions.artistRadio();
    expect(playNext).not.toHaveBeenCalled();
    expect(addToQueue).not.toHaveBeenCalled();
  });
});

describe("no playback interruption", () => {
  it("never pauses, stops, or resets TrackPlayer for any action", async () => {
    const { deps } = makeDeps();
    const actions = createPlayerMenuActions(deps);
    actions.goToAlbum();
    actions.goToArtist();
    await actions.playAlbumNext();
    await actions.addAlbumToQueue();
    await actions.artistRadio();
    expect(pause).not.toHaveBeenCalled();
    expect(stop).not.toHaveBeenCalled();
    expect(reset).not.toHaveBeenCalled();
  });
});
