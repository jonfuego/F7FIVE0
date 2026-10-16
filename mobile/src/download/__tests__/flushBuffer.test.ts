import {
  addEvent,
  clearPodcastUpTo,
  emptyBuffer,
  latestPodcastPosition,
  flush,
  orderedForFlush,
  type BufferedEvent,
} from "../flushBuffer";

describe("offline flush buffer", () => {
  it("dedupes progress by media_file_id, keeping the latest", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 10, at: 1 });
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 25, at: 2 });
    expect(b.events).toHaveLength(1);
    expect((b.events[0] as { positionSec: number }).positionSec).toBe(25);
  });

  it("keeps separate progress per media file", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 10, at: 1 });
    b = addEvent(b, { kind: "progress", mediaFileId: "m2", positionSec: 5, at: 1 });
    expect(b.events).toHaveLength(2);
  });

  it("accumulates track-plays (each is a distinct play)", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "track_play", trackId: "t1", msPlayed: 1000, completed: true, at: 1 });
    b = addEvent(b, { kind: "track_play", trackId: "t1", msPlayed: 2000, completed: true, at: 2 });
    expect(b.events).toHaveLength(2);
  });

  it("orders progress before track-plays, each by time", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "track_play", trackId: "t1", msPlayed: 1, completed: false, at: 5 });
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 1, at: 3 });
    const ordered = orderedForFlush(b);
    expect(ordered.map((e) => e.kind)).toEqual(["progress", "track_play"]);
  });

  it("flushes all events when the sender succeeds", async () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 1, at: 1 });
    b = addEvent(b, { kind: "track_play", trackId: "t1", msPlayed: 1, completed: true, at: 2 });
    const sent: BufferedEvent[] = [];
    const out = await flush(b, async (e) => {
      sent.push(e);
    });
    expect(sent).toHaveLength(2);
    expect(out.events).toHaveLength(0);
  });

  it("retains events the sender rejects", async () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 1, at: 1 });
    b = addEvent(b, { kind: "track_play", trackId: "t1", msPlayed: 1, completed: true, at: 2 });
    const out = await flush(b, async (e) => {
      if (e.kind === "track_play") throw new Error("offline again");
    });
    expect(out.events).toHaveLength(1);
    expect(out.events[0].kind).toBe("track_play");
  });
});

describe("podcast progress in the offline buffer", () => {
  const ev = (at: number, positionSec: number) =>
    ({ kind: "podcast_progress", episodeId: "ep1", positionSec, at }) as const;

  it("keeps the save taken last, even when an older one arrives after it", () => {
    let b = emptyBuffer();
    b = addEvent(b, ev(2000, 2400));
    b = addEvent(b, ev(1000, 1380));
    expect(latestPodcastPosition(b, "ep1")).toBe(2400);
    b = addEvent(b, ev(3000, 2500));
    expect(latestPodcastPosition(b, "ep1")).toBe(2500);
  });

  it("a newer save that reached the server clears the buffered one", () => {
    let b = addEvent(emptyBuffer(), ev(1000, 1380));
    b = clearPodcastUpTo(b, "ep1", 999);
    expect(latestPodcastPosition(b, "ep1")).toBe(1380);
    b = clearPodcastUpTo(b, "ep1", 1000);
    expect(latestPodcastPosition(b, "ep1")).toBeNull();
  });

  it("clearing one episode leaves the others", () => {
    let b = addEvent(emptyBuffer(), ev(1000, 10));
    b = addEvent(b, { kind: "podcast_progress", episodeId: "ep2", positionSec: 20, at: 500 });
    b = clearPodcastUpTo(b, "ep1", 5000);
    expect(latestPodcastPosition(b, "ep2")).toBe(20);
    expect(b.events).toHaveLength(1);
  });
});
