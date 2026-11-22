import { isUsableSeek, SessionResumer, sessionResumeBridge, type ResumeDeps } from "../sessionResume";
import type { LastSession } from "../lastSession";

const podcast: LastSession = {
  kind: "podcast",
  episode: { id: "ep1", title: "Ep", showTitle: "Show" },
  positionSec: 3457,
  recordedAtMs: 1,
};

function setup(over: Partial<ResumeDeps> = {}) {
  const calls: string[] = [];
  let queue = 0;
  const deps: ResumeDeps = {
    queueLength: async () => queue,
    loadSession: async () => podcast,
    restore: async (s, o) => {
      calls.push(`restore:${s.kind}:${o.play}`);
      queue = 1;
      return true;
    },
    play: async () => {
      calls.push("play");
    },
    ...over,
  };
  return { r: new SessionResumer(deps), calls, setQueue: (n: number) => (queue = n) };
}

describe("isUsableSeek", () => {
  it("takes real positions and drops ExoPlayer's unset time", () => {
    expect(isUsableSeek(0)).toBe(true);
    expect(isUsableSeek(3201.5)).toBe(true);
    expect(isUsableSeek(-9223372036854775.807)).toBe(false);
    expect(isUsableSeek(-1)).toBe(false);
    expect(isUsableSeek(Number.NaN)).toBe(false);
    expect(isUsableSeek(Number.POSITIVE_INFINITY)).toBe(false);
    expect(isUsableSeek(undefined)).toBe(false);
  });
});

describe("SessionResumer", () => {
  it("an empty player rebuilds the last session and plays", async () => {
    const t = setup();
    expect(await t.r.resumeIfEmpty()).toBe(true);
    expect(t.calls).toEqual(["restore:podcast:true"]);
  });

  it("a player with something loaded is left to play it", async () => {
    const t = setup();
    t.setQueue(3);
    expect(await t.r.resumeIfEmpty()).toBe(false);
    expect(t.calls).toEqual([]);
  });

  it("nothing saved: the caller plays as before", async () => {
    const t = setup({ loadSession: async () => null });
    expect(await t.r.resumeIfEmpty()).toBe(false);
  });

  it("two Plays at once share one rebuild", async () => {
    const t = setup();
    const [a, b] = await Promise.all([t.r.resumeIfEmpty(), t.r.resumeIfEmpty()]);
    expect([a, b]).toEqual([true, true]);
    expect(t.calls).toEqual(["restore:podcast:true"]);
  });

  it("a Play during the paused cold-start rebuild plays once it is loaded", async () => {
    const t = setup();
    const cold = t.r.resumeIfEmpty({ play: false });
    const car = t.r.resumeIfEmpty({ play: true });
    expect(await cold).toBe(true);
    expect(await car).toBe(true);
    expect(t.calls).toEqual(["restore:podcast:false", "play"]);
  });

  it("a failing rebuild never throws", async () => {
    const t = setup({ restore: async () => Promise.reject(new Error("offline")) });
    await expect(t.r.resumeIfEmpty()).resolves.toBe(false);
  });

  it("the bridge answers false with no resumer set", async () => {
    sessionResumeBridge.set(null);
    expect(await sessionResumeBridge.resumeIfEmpty()).toBe(false);
    const t = setup();
    sessionResumeBridge.set(t.r);
    expect(await sessionResumeBridge.resumeIfEmpty()).toBe(true);
    sessionResumeBridge.set(null);
  });
});
