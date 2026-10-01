import {
  doneItems,
  localFileName,
  restoreItems,
  canEnqueue,
  initialState,
  nextToStart,
  reduce,
  usedBytes,
  type DownloadState,
} from "../queue";

describe("download queue state machine", () => {
  it("enqueues a new item as queued", () => {
    const s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    expect(s.items).toHaveLength(1);
    expect(s.items[0]).toMatchObject({ id: "a", status: "queued", progress: 0 });
  });

  it("is idempotent for an already-queued item", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "enqueue", id: "a", title: "A" });
    expect(s.items).toHaveLength(1);
  });

  it("re-queues a canceled or errored item", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "cancel", id: "a" });
    expect(s.items[0].status).toBe("canceled");
    s = reduce(s, { type: "enqueue", id: "a", title: "A" });
    expect(s.items[0].status).toBe("queued");
  });

  it("moves through start -> progress -> complete", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "start", id: "a" });
    expect(s.items[0].status).toBe("downloading");
    s = reduce(s, { type: "progress", id: "a", bytes: 50, totalBytes: 100 });
    expect(s.items[0].progress).toBeCloseTo(0.5, 5);
    s = reduce(s, { type: "complete", id: "a", localPath: "/x/a.m4a", bytes: 100 });
    expect(s.items[0]).toMatchObject({ status: "done", progress: 1, localPath: "/x/a.m4a", bytes: 100 });
  });

  it("marks failures with an error message", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "fail", id: "a", error: "network" });
    expect(s.items[0]).toMatchObject({ status: "error", error: "network" });
  });

  it("removes an item entirely", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "remove", id: "a" });
    expect(s.items).toHaveLength(0);
  });

  it("only starts one download at a time (FIFO of queued)", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "enqueue", id: "b", title: "B" });
    expect(nextToStart(s)?.id).toBe("a");
    s = reduce(s, { type: "start", id: "a" });
    // While a is downloading, nothing else starts.
    expect(nextToStart(s)).toBeNull();
    s = reduce(s, { type: "complete", id: "a", localPath: "/x/a", bytes: 10 });
    expect(nextToStart(s)?.id).toBe("b");
  });

  it("computes used bytes from completed downloads only", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "complete", id: "a", localPath: "/x/a", bytes: 500 });
    s = reduce(s, { type: "enqueue", id: "b", title: "B" });
    s = reduce(s, { type: "start", id: "b" });
    s = reduce(s, { type: "progress", id: "b", bytes: 300, totalBytes: 1000 });
    expect(usedBytes(s)).toBe(500);
  });

  it("enforces the storage limit for new enqueues", () => {
    let s: DownloadState = reduce(initialState(1000), { type: "enqueue", id: "a", title: "A" });
    s = reduce(s, { type: "complete", id: "a", localPath: "/x/a", bytes: 1000 });
    expect(canEnqueue(s)).toBe(false);
    s = reduce(s, { type: "setLimit", bytes: 2000 });
    expect(canEnqueue(s)).toBe(true);
    // Unlimited when 0.
    s = reduce(s, { type: "setLimit", bytes: 0 });
    expect(canEnqueue(s)).toBe(true);
  });
});

describe("download restore + metadata", () => {
  it("keeps metadata on enqueue so offline mode can play without the network", () => {
    const s = reduce(initialState(), {
      type: "enqueue",
      id: "m1",
      title: "Song",
      kind: "track",
      meta: { trackId: "t1", artist: "A", container: "flac" },
    });
    expect(s.items[0].kind).toBe("track");
    expect(s.items[0].meta?.trackId).toBe("t1");
  });

  it("restoreItems keeps done files that exist, re-queues in-flight, drops the rest", () => {
    const restored = restoreItems(
      [
        { id: "a", title: "A", status: "done", progress: 1, bytes: 10, localPath: "file:///a.flac" },
        { id: "b", title: "B", status: "done", progress: 1, bytes: 10, localPath: "file:///gone.flac" },
        { id: "c", title: "C", status: "downloading", progress: 0.4, bytes: 4 },
        { id: "d", title: "D", status: "error", progress: 0, bytes: 0, error: "x" },
      ],
      (it) => it.localPath === "file:///a.flac",
      1024,
    );
    expect(restored.items.map((i) => [i.id, i.status])).toEqual([
      ["a", "done"],
      ["c", "queued"],
    ]);
    expect(restored.storageLimitBytes).toBe(1024);
  });

  it("doneItems filters by kind (untyped legacy items count as tracks)", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "t", title: "T" });
    s = reduce(s, { type: "complete", id: "t", localPath: "file:///t", bytes: 1 });
    s = reduce(s, { type: "enqueue", id: "v", title: "V", kind: "movie" });
    s = reduce(s, { type: "complete", id: "v", localPath: "file:///v", bytes: 1 });
    expect(doneItems(s, "track").map((i) => i.id)).toEqual(["t"]);
    expect(doneItems(s, "movie").map((i) => i.id)).toEqual(["v"]);
  });

  it("localFileName appends a sanitized container extension", () => {
    expect(localFileName("id1", "flac")).toBe("id1.flac");
    expect(localFileName("id1", "M4A")).toBe("id1.m4a");
    expect(localFileName("id1", null)).toBe("id1");
    expect(localFileName("id1", "../x")).toBe("id1.x");
  });
});
