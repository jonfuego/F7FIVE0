import {
  CACHE_MAX_AGE_MS,
  CACHE_MAX_ATTEMPTS,
  cacheBytes,
  cachedPath,
  cacheReduce,
  emptyCache,
  evictable,
  musicLookahead,
  nextCacheToStart,
  restoreCache,
  type CacheState,
} from "../autoCache";

const DAY = 24 * 60 * 60 * 1000;

function req(s: CacheState, id: string, kind: "track" | "podcast", now = 0): CacheState {
  return cacheReduce(s, { type: "request", id, kind, title: id, now });
}

describe("auto cache", () => {
  it("queues a played item once and saves one at a time", () => {
    let s = req(emptyCache(), "a", "podcast");
    s = req(s, "a", "podcast", 5);
    s = req(s, "b", "track");
    expect(s.entries).toHaveLength(2);
    expect(nextCacheToStart(s)?.id).toBe("a");
    s = cacheReduce(s, { type: "start", id: "a" });
    expect(nextCacheToStart(s)).toBeNull();
    s = cacheReduce(s, { type: "complete", id: "a", localPath: "file:///a.mp3", bytes: 100 });
    expect(nextCacheToStart(s)?.id).toBe("b");
    expect(cachedPath(s, "a")).toBe("file:///a.mp3");
    expect(cachedPath(s, "b")).toBeUndefined();
    expect(cacheBytes(s)).toBe(100);
  });

  it("a podcast episode goes once it counts as played", () => {
    let s = req(emptyCache(), "ep", "podcast", 0);
    s = cacheReduce(s, { type: "start", id: "ep" });
    s = cacheReduce(s, { type: "complete", id: "ep", localPath: "x", bytes: 1 });
    expect(evictable(s, 1)).toHaveLength(0);
    s = cacheReduce(s, { type: "played", id: "ep", now: 1 });
    expect(evictable(s, 2).map((e) => e.id)).toEqual(["ep"]);
    // ...but not while it is loaded in the player.
    expect(evictable(s, 2, new Set(["ep"]))).toHaveLength(0);
  });

  it("anything not played for 7 days goes; playing it again keeps it", () => {
    let s = req(emptyCache(), "song", "track", 0);
    expect(evictable(s, CACHE_MAX_AGE_MS - 1)).toHaveLength(0);
    expect(evictable(s, CACHE_MAX_AGE_MS).map((e) => e.id)).toEqual(["song"]);
    s = req(s, "song", "track", 6 * DAY);
    expect(evictable(s, 8 * DAY)).toHaveLength(0);
  });

  it("a played music track is not removed for being played (only age counts)", () => {
    let s = req(emptyCache(), "song", "track", 0);
    s = cacheReduce(s, { type: "played", id: "song", now: 1 });
    expect(evictable(s, 2)).toHaveLength(0);
  });

  it("playing an episode again clears its played mark", () => {
    let s = req(emptyCache(), "ep", "podcast", 0);
    s = cacheReduce(s, { type: "played", id: "ep", now: 1 });
    s = req(s, "ep", "podcast", 2);
    expect(evictable(s, 3)).toHaveLength(0);
  });

  it("a failed save is tried again on a later play, then given up", () => {
    let s = req(emptyCache(), "a", "track");
    for (let i = 0; i < CACHE_MAX_ATTEMPTS; i++) {
      s = cacheReduce(s, { type: "start", id: "a" });
      s = cacheReduce(s, { type: "fail", id: "a" });
      s = req(s, "a", "track", i + 1);
    }
    expect(s.entries[0].status).toBe("error");
    expect(nextCacheToStart(s)).toBeNull();
    expect(evictable(s, 10).map((e) => e.id)).toEqual(["a"]);
  });

  it("never removes one that is downloading", () => {
    let s = req(emptyCache(), "a", "track", 0);
    s = cacheReduce(s, { type: "start", id: "a" });
    expect(evictable(s, 30 * DAY)).toHaveLength(0);
  });

  it("restore keeps files that are still there and re-queues a running save", () => {
    const s = restoreCache(
      [
        { id: "a", kind: "track", title: "a", status: "done", bytes: 1, localPath: "pa", lastPlayedAt: 0, attempts: 1 },
        { id: "b", kind: "track", title: "b", status: "done", bytes: 1, localPath: "pb", lastPlayedAt: 0, attempts: 1 },
        { id: "c", kind: "podcast", title: "c", status: "downloading", bytes: 0, lastPlayedAt: 0, attempts: 1 },
      ],
      (e) => e.id !== "b",
    );
    expect(s.entries.map((e) => `${e.id}:${e.status}`)).toEqual(["a:done", "c:queued"]);
  });

  it("music saves the playing track and the next two", () => {
    expect(musicLookahead([1, 2, 3, 4, 5], 1)).toEqual([2, 3, 4]);
    expect(musicLookahead([1, 2], 1)).toEqual([2]);
    expect(musicLookahead([1, 2], -1)).toEqual([]);
  });
});
