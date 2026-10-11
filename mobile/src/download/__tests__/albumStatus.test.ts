import {
  albumDownloadSummary,
  downloadConfirmation,
  trackDownloadStatus,
  trackStatusText,
} from "../albumStatus";
import type { DownloadItem, DownloadState, DownloadStatus } from "../queue";

function store(statuses: Record<string, DownloadStatus>): DownloadState {
  const items: DownloadItem[] = Object.entries(statuses).map(([id, status]) => ({
    id,
    title: id,
    status,
    progress: status === "done" ? 1 : 0,
    bytes: 0,
  }));
  return { items, storageLimitBytes: 0 };
}

describe("trackDownloadStatus", () => {
  const s = store({ q: "queued", d: "downloading", ok: "done", bad: "error", c: "canceled" });
  it("maps store statuses to track statuses", () => {
    expect(trackDownloadStatus(s, "q")).toBe("queued");
    expect(trackDownloadStatus(s, "d")).toBe("downloading");
    expect(trackDownloadStatus(s, "ok")).toBe("done");
    expect(trackDownloadStatus(s, "bad")).toBe("failed");
  });
  it("treats canceled, unknown and missing ids as none", () => {
    expect(trackDownloadStatus(s, "c")).toBe("none");
    expect(trackDownloadStatus(s, "nope")).toBe("none");
    expect(trackDownloadStatus(s, undefined)).toBe("none");
  });
  it("has screen reader text for every state but none", () => {
    expect(trackStatusText("none")).toBeNull();
    expect(trackStatusText("queued")).toBe("queued for download");
    expect(trackStatusText("downloading")).toBe("downloading");
    expect(trackStatusText("done")).toBe("downloaded");
    expect(trackStatusText("failed")).toBe("download failed");
  });
});

describe("albumDownloadSummary", () => {
  const ids = ["a", "b", "c", "d"];
  it("says nothing when no track is in the store", () => {
    const r = albumDownloadSummary(store({ other: "done" }), ids);
    expect(r.state).toBe("none");
    expect(r.label).toBeNull();
  });
  it("says nothing for an album with no files", () => {
    expect(albumDownloadSummary(store({}), []).label).toBeNull();
  });
  it("is done when every track is done", () => {
    const r = albumDownloadSummary(store({ a: "done", b: "done", c: "done", d: "done" }), ids);
    expect(r).toMatchObject({ state: "done", label: "Downloaded", done: 4 });
  });
  it("is partial when some are done and nothing is running", () => {
    const r = albumDownloadSummary(store({ a: "done", b: "done" }), ids);
    expect(r).toMatchObject({ state: "partial", label: "2 of 4 downloaded" });
  });
  it("is active while anything is queued or downloading", () => {
    const r = albumDownloadSummary(store({ a: "done", b: "downloading", c: "queued", d: "queued" }), ids);
    expect(r).toMatchObject({ state: "active", label: "Downloading, 1 of 4 done", queued: 2, downloading: 1 });
  });
  it("reports failed tracks alongside the rest", () => {
    const r = albumDownloadSummary(store({ a: "done", b: "done", c: "done", d: "error" }), ids);
    expect(r).toMatchObject({ state: "failed", label: "3 of 4 downloaded, 1 failed", failed: 1 });
    const active = albumDownloadSummary(store({ a: "done", b: "queued", c: "error" }), ids);
    expect(active.label).toBe("Downloading, 1 of 4 done, 1 failed");
  });
  it("is failed when nothing finished and tracks failed", () => {
    const r = albumDownloadSummary(store({ a: "error", b: "error" }), ids);
    expect(r).toMatchObject({ state: "failed", label: "2 of 4 failed" });
  });
  it("ignores canceled tracks", () => {
    expect(albumDownloadSummary(store({ a: "canceled" }), ids).state).toBe("none");
  });
});

describe("downloadConfirmation", () => {
  const ids = ["a", "b", "c"];
  it("names the number of tracks queued", () => {
    expect(downloadConfirmation(store({}), ids, 3)).toBe("Downloading 3 tracks");
  });
  it("uses the singular for one track", () => {
    expect(downloadConfirmation(store({}), ["a"], 1)).toBe("Downloading 1 track");
  });
  it("says Nothing to download for an album with no files", () => {
    expect(downloadConfirmation(store({}), [], 0)).toBe("Nothing to download");
  });
  it("says Already downloaded when every track is done", () => {
    expect(downloadConfirmation(store({ a: "done", b: "done", c: "done" }), ids, 3)).toBe("Already downloaded");
  });
  it("says Already downloading when the rest are queued or running", () => {
    expect(downloadConfirmation(store({ a: "done", b: "queued", c: "downloading" }), ids, 3)).toBe(
      "Already downloading",
    );
  });
  it("counts only the new tracks and mentions the finished ones", () => {
    expect(downloadConfirmation(store({ a: "done" }), ids, 3)).toBe("Downloading 2 tracks (1 already downloaded)");
  });
  it("counts failed and canceled tracks as new, since queueing retries them", () => {
    expect(downloadConfirmation(store({ a: "error", b: "canceled", c: "done" }), ids, 3)).toBe(
      "Downloading 2 tracks (1 already downloaded)",
    );
  });
  it("reports the storage limit when the store refused the tracks", () => {
    expect(downloadConfirmation(store({}), ids, 0)).toBe("Storage limit reached");
  });
});
