import { failedItems, initialState, reduce, retryDownload, nextToStart, type DownloadState } from "../queue";

function failedState(): DownloadState {
  let s = initialState();
  s = reduce(s, {
    type: "enqueue",
    id: "a",
    title: "King of Suede",
    kind: "track",
    meta: { artist: "Weird Al", group: "In 3-D" },
  });
  s = reduce(s, { type: "start", id: "a" });
  s = reduce(s, { type: "progress", id: "a", bytes: 40, totalBytes: 100 });
  return reduce(s, { type: "fail", id: "a", error: "Software caused connection abort" });
}

describe("retryDownload", () => {
  it("puts a failed item back in the queue and clears the error and partial progress", () => {
    const s = retryDownload(failedState(), "a");
    expect(s.items[0]).toMatchObject({ id: "a", status: "queued", progress: 0, bytes: 0 });
    expect(s.items[0].error).toBeUndefined();
    expect(s.items[0].totalBytes).toBeUndefined();
  });

  it("keeps the title, kind and meta so an album track stays grouped", () => {
    const item = retryDownload(failedState(), "a").items[0];
    expect(item.title).toBe("King of Suede");
    expect(item.kind).toBe("track");
    expect(item.meta).toEqual({ artist: "Weird Al", group: "In 3-D" });
  });

  it("makes the item the next one to start", () => {
    expect(nextToStart(retryDownload(failedState(), "a"))?.id).toBe("a");
  });

  it("does nothing for items that are not failed", () => {
    let s = reduce(initialState(), { type: "enqueue", id: "q", title: "Q" });
    s = reduce(s, { type: "enqueue", id: "d", title: "D" });
    s = reduce(s, { type: "start", id: "d" });
    s = reduce(s, { type: "complete", id: "d", localPath: "/x/d.m4a", bytes: 10 });
    s = reduce(s, { type: "enqueue", id: "c", title: "C" });
    s = reduce(s, { type: "cancel", id: "c" });
    expect(retryDownload(s, "q")).toBe(s);
    expect(retryDownload(s, "d")).toBe(s);
    expect(retryDownload(s, "c")).toBe(s);
    expect(retryDownload(s, "missing")).toBe(s);
  });

  it("only touches the retried item", () => {
    let s = failedState();
    s = reduce(s, { type: "enqueue", id: "b", title: "B" });
    s = reduce(s, { type: "start", id: "b" });
    s = reduce(s, { type: "fail", id: "b", error: "http_500" });
    const after = retryDownload(s, "a");
    expect(after.items.find((i) => i.id === "a")?.status).toBe("queued");
    expect(after.items.find((i) => i.id === "b")).toMatchObject({ status: "error", error: "http_500" });
  });

  it("works through the reducer's retry action", () => {
    const s = reduce(failedState(), { type: "retry", id: "a" });
    expect(s.items[0].status).toBe("queued");
  });

  it("lists failed items for the Downloads screen", () => {
    expect(failedItems(failedState()).map((i) => i.id)).toEqual(["a"]);
    expect(failedItems(retryDownload(failedState(), "a"))).toEqual([]);
  });
});
