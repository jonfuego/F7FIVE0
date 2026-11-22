import type { QueueDTO } from "@/api/types";
import {
  adoptNativeQueue,
  chooseSession,
  metasFromServerQueue,
  parseLastSession,
  resumePositionFor,
  songFromMeta,
  type LastSession,
} from "../lastSession";

const meta = (n: number) => ({ mediaFileId: `mf${n}`, trackId: `t${n}`, title: `Track ${n}`, durationSec: 200 });

const music: LastSession = {
  kind: "music",
  items: [meta(1), meta(2), meta(3), meta(4)],
  index: 3,
  positionSec: 95,
  recordedAtMs: Date.parse("2026-11-17T16:00:00Z"),
};

function serverQueue(ids: number[], index: number, updatedAt: string): QueueDTO {
  return {
    items: ids.map((n) => ({ media_file_id: `mf${n}`, title: `Track ${n}`, track_id: `t${n}`, duration_sec: 200 })),
    current_index: index,
    repeat_mode: "off",
    shuffle: false,
    updated_at: updatedAt,
  };
}

describe("parseLastSession", () => {
  it("keeps a valid music record and clamps its index", () => {
    expect(parseLastSession(music)).toEqual(music);
    expect((parseLastSession({ ...music, index: 9 }) as { index: number }).index).toBe(3);
  });

  it("keeps a valid podcast record", () => {
    const p = { kind: "podcast", episode: { id: "ep1", title: "Ep", showTitle: "Show" }, positionSec: 3457, recordedAtMs: 1 };
    expect(parseLastSession(p)).toMatchObject({ kind: "podcast", positionSec: 3457, episode: { id: "ep1", showTitle: "Show" } });
  });

  it("drops anything unusable", () => {
    expect(parseLastSession(null)).toBeNull();
    expect(parseLastSession("x")).toBeNull();
    expect(parseLastSession({ kind: "music", items: [], index: 0, positionSec: 0, recordedAtMs: 1 })).toBeNull();
    expect(parseLastSession({ kind: "podcast", episode: {}, positionSec: 0, recordedAtMs: 1 })).toBeNull();
    expect(parseLastSession({ ...music, positionSec: "95" })).toBeNull();
    expect(parseLastSession({ ...music, kind: "video" })).toBeNull();
  });
});

describe("chooseSession", () => {
  it("the phone's record when there is no server queue", () => {
    expect(chooseSession(music, null)).toBe(music);
  });

  it("the server queue when the phone has nothing (track at 0)", () => {
    const s = chooseSession(null, serverQueue([1, 2, 3], 2, "2026-11-17T16:00:00Z"));
    expect(s).toMatchObject({ kind: "music", index: 2, positionSec: 0 });
  });

  it("the phone's record when the server queue is only its echo, even if written later", () => {
    const s = chooseSession(music, serverQueue([1, 2, 3, 4], 0, "2026-11-17T18:00:00Z"));
    expect(s).toBe(music);
  });

  it("a different server queue written well after the phone's record wins", () => {
    const s = chooseSession(music, serverQueue([7, 8], 1, "2026-11-17T18:00:00Z"));
    expect(s).toMatchObject({ kind: "music", index: 1, items: [{ mediaFileId: "mf7" }, { mediaFileId: "mf8" }] });
  });

  it("an older server queue loses to a podcast on the phone", () => {
    const pod: LastSession = { kind: "podcast", episode: { id: "e", title: "E", showTitle: "S" }, positionSec: 10, recordedAtMs: music.recordedAtMs };
    expect(chooseSession(pod, serverQueue([7], 0, "2026-11-17T15:00:00Z"))).toBe(pod);
  });
});

describe("helpers", () => {
  it("metasFromServerQueue maps the queue rows", () => {
    expect(metasFromServerQueue(serverQueue([1], 0, "2026-11-17T15:00:00Z"))[0]).toMatchObject({ mediaFileId: "mf1", trackId: "t1", title: "Track 1" });
    expect(metasFromServerQueue(null)).toEqual([]);
  });

  it("songFromMeta builds a playable song for the same media file", () => {
    const s = songFromMeta(meta(2));
    expect(s.id).toBe("t2");
    expect(s.media_files[0].id).toBe("mf2");
    expect(songFromMeta({ mediaFileId: "mf9", title: "x" }).id).toBe("mf9");
  });

  it("resumePositionFor skips the first seconds and the very end", () => {
    expect(resumePositionFor(95.7, 200)).toBe(95);
    expect(resumePositionFor(2, 200)).toBe(0);
    expect(resumePositionFor(199, 200)).toBe(0);
    expect(resumePositionFor(500, null)).toBe(500);
  });
});

describe("adoptNativeQueue", () => {
  const song = (n: number) => ({ id: `t${n}`, title: `Track ${n}`, mediaFileId: `mf${n}`, trackId: `t${n}`, durationSec: 200 });

  it("takes over a music queue at the playing track", () => {
    const a = adoptNativeQueue([song(1), song(2), song(3)], 2);
    expect(a?.index).toBe(2);
    expect(a?.metas.map((m) => m.mediaFileId)).toEqual(["mf1", "mf2", "mf3"]);
    expect(a?.episode).toBeNull();
  });

  it("an episode comes back in podcast mode with its details", () => {
    const ep = { id: "ep1", title: "Ep", artist: "Show", mediaFileId: "ep1", episodeId: "ep1", kind: "podcast", podcastId: "p1", durationSec: 9598 };
    expect(adoptNativeQueue([ep], 0)?.episode).toEqual({ id: "ep1", podcastId: "p1", title: "Ep", showTitle: "Show", coverPath: null, durationSec: 9598 });
  });

  it("nothing to take over: empty, or tracks the app did not make", () => {
    expect(adoptNativeQueue([], 0)).toBeNull();
    expect(adoptNativeQueue([{ id: "x", title: "x" }], 0)).toBeNull();
  });

  it("a bad index falls back to the first track", () => {
    expect(adoptNativeQueue([song(1), song(2)], 7)?.index).toBe(0);
    expect(adoptNativeQueue([song(1), song(2)], null)?.index).toBe(0);
  });
});
