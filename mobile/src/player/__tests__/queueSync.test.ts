import {
  buildServerQueueItems,
  clampCurrentIndex,
  shouldHydrateFromServer,
  type QueueSnapshotItem,
} from "../queueSync";

describe("queue sync", () => {
  const metas: QueueSnapshotItem[] = [
    { mediaFileId: "mf1", trackId: "t1", title: "One", artist: "A", album: "Alb", artPath: "/c1.jpg", durationSec: 200 },
    { mediaFileId: "mf2", trackId: "t2", title: "Two" },
  ];

  it("maps in-memory metas to the server queue payload shape", () => {
    const items = buildServerQueueItems(metas);
    expect(items).toHaveLength(2);
    expect(items[0]).toEqual({
      media_file_id: "mf1",
      title: "One",
      track_id: "t1",
      artist_name: "A",
      album_title: "Alb",
      cover_path: "/c1.jpg",
      duration_sec: 200,
    });
    // Missing optional fields serialize as null (backend allows extra/null).
    expect(items[1]).toEqual({
      media_file_id: "mf2",
      title: "Two",
      track_id: "t2",
      artist_name: null,
      album_title: null,
      cover_path: null,
      duration_sec: null,
    });
  });

  it("clamps the current index into range and nulls it when empty", () => {
    expect(clampCurrentIndex(1, 3)).toBe(1);
    expect(clampCurrentIndex(-5, 3)).toBe(0);
    expect(clampCurrentIndex(9, 3)).toBe(2);
    expect(clampCurrentIndex(0, 0)).toBeNull();
  });

  it("only hydrates from the server when local is empty and server has items", () => {
    expect(shouldHydrateFromServer(0, 5)).toBe(true);
    expect(shouldHydrateFromServer(2, 5)).toBe(false);
    expect(shouldHydrateFromServer(0, 0)).toBe(false);
  });

  it("maps an empty queue to an empty payload", () => {
    expect(buildServerQueueItems([])).toEqual([]);
  });

  it("clamps boundary indices exactly", () => {
    expect(clampCurrentIndex(0, 3)).toBe(0);
    expect(clampCurrentIndex(2, 3)).toBe(2);
    expect(clampCurrentIndex(3, 3)).toBe(2);
  });
});
