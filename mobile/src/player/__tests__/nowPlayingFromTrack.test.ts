import { metaFromTrack, nowPlayingFromTrack } from "../nowPlayingFromTrack";

const sheWantsRevenge = {
  id: "t-swr-3",
  title: "Broken Promises For Broken Hearts",
  artist: "She Wants Revenge",
  album: "She Wants Revenge",
  artwork: "https://x/art/swr.jpg?sig=1",
  mediaFileId: "mf-swr-3",
  trackId: "t-swr-3",
  albumId: "al-swr",
  artistId: "ar-swr",
  artPath: "/api/art/album/al-swr",
  durationSec: 240,
};

const state808 = {
  id: "t-808-1",
  title: "Pacific State",
  artist: "808 State",
  album: "Blueprint",
  artwork: "https://x/art/808.jpg?sig=2",
  mediaFileId: "mf-808-1",
  trackId: "t-808-1",
  albumId: "al-808",
  artistId: "ar-808",
  artPath: "/api/art/album/al-808",
  durationSec: 300,
};

describe("nowPlayingFromTrack", () => {
  it("returns null when there is no track", () => {
    expect(nowPlayingFromTrack(null)).toBeNull();
    expect(nowPlayingFromTrack(undefined)).toBeNull();
  });

  it("takes the album id, art path and media file id from the track passed in", () => {
    expect(nowPlayingFromTrack(sheWantsRevenge)).toMatchObject({
      title: "Broken Promises For Broken Hearts",
      artist: "She Wants Revenge",
      albumId: "al-swr",
      artistId: "ar-swr",
      artPath: "/api/art/album/al-swr",
      mediaFileId: "mf-swr-3",
      trackId: "t-swr-3",
    });
  });

  it("gives different values for tracks from different albums", () => {
    const a = nowPlayingFromTrack(sheWantsRevenge);
    const b = nowPlayingFromTrack(state808);
    expect(a?.albumId).not.toBe(b?.albumId);
    expect(a?.artPath).not.toBe(b?.artPath);
    expect(a?.mediaFileId).not.toBe(b?.mediaFileId);
  });

  it("falls back to the artwork URL when the track has no art path", () => {
    const np = nowPlayingFromTrack({ ...state808, artPath: undefined });
    expect(np?.artPath).toBe("https://x/art/808.jpg?sig=2");
  });

  it("reports a podcast track as a podcast with its episode id", () => {
    const np = nowPlayingFromTrack({
      id: "ep-9",
      title: "Episode nine",
      artist: "The Show",
      mediaFileId: "ep-9",
      kind: "podcast",
      episodeId: "ep-9",
      podcastId: "pod-1",
      artPath: "/api/art/podcast/pod-1",
    });
    expect(np).toMatchObject({ kind: "podcast", episodeId: "ep-9", podcastId: "pod-1", mediaFileId: "ep-9" });
    expect(np?.albumId).toBeNull();
  });

  it("does not report a kind for a music track", () => {
    expect(nowPlayingFromTrack(state808)?.kind).toBeUndefined();
  });
});

describe("metaFromTrack", () => {
  it("rebuilds the queue meta from the track's own fields", () => {
    expect(metaFromTrack(sheWantsRevenge)).toMatchObject({
      mediaFileId: "mf-swr-3",
      trackId: "t-swr-3",
      albumId: "al-swr",
      artPath: "/api/art/album/al-swr",
      durationSec: 240,
    });
  });

  it("is null for a track with no media file id", () => {
    expect(metaFromTrack({ id: "x", title: "No meta" })).toBeNull();
    expect(metaFromTrack(null)).toBeNull();
  });
});
