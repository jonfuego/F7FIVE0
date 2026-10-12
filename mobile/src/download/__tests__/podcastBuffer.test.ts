import { addEvent, emptyBuffer, flush, orderedForFlush, type BufferedEvent } from "../flushBuffer";

describe("podcast progress through the offline buffer", () => {
  it("keeps only the latest position per episode", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "podcast_progress", episodeId: "e1", positionSec: 10, durationSec: 3600, at: 1 });
    b = addEvent(b, { kind: "podcast_progress", episodeId: "e1", positionSec: 700, durationSec: 3600, at: 2 });
    b = addEvent(b, { kind: "podcast_progress", episodeId: "e2", positionSec: 5, at: 2 });
    expect(b.events).toHaveLength(2);
    const e1 = b.events.find((e) => e.kind === "podcast_progress" && e.episodeId === "e1");
    expect(e1 && e1.kind === "podcast_progress" ? e1.positionSec : -1).toBe(700);
  });

  it("does not mix with watch progress for the same id", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "progress", mediaFileId: "same", positionSec: 1, at: 1 });
    b = addEvent(b, { kind: "podcast_progress", episodeId: "same", positionSec: 2, at: 2 });
    expect(b.events).toHaveLength(2);
  });

  it("sends progress first, then podcast progress, then track plays", () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "track_play", trackId: "t", msPlayed: 1, completed: true, at: 1 });
    b = addEvent(b, { kind: "podcast_progress", episodeId: "e1", positionSec: 9, at: 2 });
    b = addEvent(b, { kind: "progress", mediaFileId: "m1", positionSec: 3, at: 3 });
    expect(orderedForFlush(b).map((e) => e.kind)).toEqual(["progress", "podcast_progress", "track_play"]);
  });

  it("flushes on reconnect and keeps what the server refuses", async () => {
    let b = emptyBuffer();
    b = addEvent(b, { kind: "podcast_progress", episodeId: "e1", positionSec: 9, durationSec: 100, at: 1 });
    b = addEvent(b, { kind: "podcast_progress", episodeId: "e2", positionSec: 4, at: 2 });
    const sent: BufferedEvent[] = [];
    const out = await flush(b, async (e) => {
      sent.push(e);
      if (e.kind === "podcast_progress" && e.episodeId === "e2") throw new Error("offline again");
    });
    expect(sent).toHaveLength(2);
    expect(out.events).toHaveLength(1);
    expect(out.events[0].kind === "podcast_progress" && out.events[0].episodeId).toBe("e2");
  });
});
