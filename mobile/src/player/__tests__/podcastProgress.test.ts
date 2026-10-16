import { MIN_TICK_GAP_MS, PodcastProgressSaver, podcastSaverBridge, type PodcastSave, type PodcastSaverDeps } from "../podcastProgress";

function setup(over: Partial<PodcastSaverDeps> = {}) {
  let clock = 1_000_000;
  const sent: PodcastSave[] = [];
  const buffered: PodcastSave[] = [];
  const cleared: [string, number][] = [];
  const state = { active: "ep1" as string | null, position: 600, duration: 3600, playing: true, online: true };
  const deps: PodcastSaverDeps = {
    currentEpisode: () => ({ episodeId: "ep1", durationSec: 3600 }),
    activeTrackId: async () => state.active,
    progress: async () => ({ position: state.position, duration: state.duration }),
    isPlaying: async () => state.playing,
    online: () => state.online,
    send: async (s) => {
      sent.push(s);
    },
    buffer: (s) => buffered.push(s),
    clearBuffered: (id, at) => cleared.push([id, at]),
    now: () => clock,
    ...over,
  };
  const saver = new PodcastProgressSaver(deps);
  return { saver, sent, buffered, cleared, state, advance: (ms: number) => (clock += ms), now: () => clock };
}

describe("PodcastProgressSaver", () => {
  it("a tick saves the native position with the time it was read", async () => {
    const t = setup();
    const s = await t.saver.save("tick");
    expect(s).toEqual({ episodeId: "ep1", positionSec: 600, durationSec: 3600, recordedAtMs: t.now(), client: "phone-tick" });
    expect(t.sent).toHaveLength(1);
    expect(t.cleared).toEqual([["ep1", t.now()]]);
  });

  it("a tick right after another save is skipped, a pause is not", async () => {
    const t = setup();
    await t.saver.save("tick");
    t.advance(MIN_TICK_GAP_MS - 1);
    expect(await t.saver.save("tick")).toBeNull();
    expect(await t.saver.save("pause")).not.toBeNull();
    t.advance(MIN_TICK_GAP_MS);
    expect(await t.saver.save("tick")).not.toBeNull();
    expect(t.sent.map((s) => s.client)).toEqual(["phone-tick", "phone-pause", "phone-tick"]);
  });

  it("a tick while paused saves nothing; a pause save does", async () => {
    const t = setup();
    t.state.playing = false;
    expect(await t.saver.save("tick")).toBeNull();
    expect((await t.saver.save("pause"))?.positionSec).toBe(600);
  });

  it("never saves another track's position (after a reset, or music loaded)", async () => {
    const t = setup();
    t.state.active = null;
    expect(await t.saver.save("pause")).toBeNull();
    t.state.active = "some-song";
    expect(await t.saver.save("pause")).toBeNull();
    expect(t.sent).toHaveLength(0);
  });

  it("saves nothing while an episode is loading", async () => {
    const t = setup();
    t.saver.suspend();
    t.state.position = 0;
    expect(await t.saver.save("pause")).toBeNull();
    t.saver.resume();
    t.state.position = 2400;
    expect((await t.saver.save("pause"))?.positionSec).toBe(2400);
  });

  it("offline, and a failed send, go to the buffer and clear nothing", async () => {
    const t = setup();
    t.state.online = false;
    await t.saver.save("pause");
    const failing = setup({ send: async () => Promise.reject(new Error("502")) });
    await failing.saver.save("pause");
    expect(t.buffered).toHaveLength(1);
    expect(failing.buffered).toHaveLength(1);
    expect(t.cleared).toHaveLength(0);
    expect(failing.cleared).toHaveLength(0);
  });

  it("the end save reports the full length so the episode reads as played", async () => {
    const t = setup();
    t.state.position = 3590;
    t.state.active = null;
    const s = await t.saver.save("end");
    expect(s?.positionSec).toBe(3600);
    expect(s?.client).toBe("phone-end");
  });

  it("a native error never throws", async () => {
    const t = setup({ progress: async () => Promise.reject(new Error("not ready")) });
    await expect(t.saver.save("pause")).resolves.toBeNull();
  });

  it("the bridge calls whichever saver is set", async () => {
    const t = setup();
    podcastSaverBridge.set(null);
    expect(await podcastSaverBridge.save("pause")).toBeNull();
    podcastSaverBridge.set(t.saver);
    expect(await podcastSaverBridge.save("pause")).not.toBeNull();
    podcastSaverBridge.set(null);
  });
});

describe("PodcastProgressSaver start guard", () => {
  it("for a minute, a tick well short of the start place is not saved; a pause is", async () => {
    const t = setup();
    t.saver.resume(2400);
    t.state.position = 12; // the seek has not landed
    expect(await t.saver.save("tick")).toBeNull();
    t.state.position = 2410;
    t.advance(MIN_TICK_GAP_MS);
    expect((await t.saver.save("tick"))?.positionSec).toBe(2410);
    t.state.position = 0; // the listener went back to the start on purpose
    expect((await t.saver.save("pause"))?.positionSec).toBe(0);
  });

  it("the guard ends after a minute", async () => {
    const t = setup();
    t.saver.resume(2400);
    t.state.position = 100;
    t.advance(60_000);
    expect((await t.saver.save("tick"))?.positionSec).toBe(100);
  });

  it("no guard for an episode started near the beginning", async () => {
    const t = setup();
    t.saver.resume(10);
    t.state.position = 0;
    expect((await t.saver.save("tick"))?.positionSec).toBe(0);
  });
});
