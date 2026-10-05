import {
  PlayerEmitter,
  trackPlayerController,
  videoController,
} from "@/player/playerController";

describe("PlayerEmitter", () => {
  it("delivers events to subscribers and unsubscribes", () => {
    const e = new PlayerEmitter();
    const seen: number[] = [];
    const off = e.on("position", (p) => seen.push(p));
    e.emit("position", 1);
    e.emit("position", 2);
    off();
    e.emit("position", 3);
    expect(seen).toEqual([1, 2]);
  });
});

describe("videoController", () => {
  it("drives paused/rate and re-bases seeks by the HLS offset", () => {
    const seeks: number[] = [];
    let paused = false;
    let rate = 1;
    const c = videoController({
      getRef: () => ({ seek: (s: number) => seeks.push(s) }),
      getBase: () => 40,
      getPosition: () => 47,
      getPaused: () => paused,
      setPaused: (p) => {
        paused = p;
      },
      setRate: (r) => {
        rate = r;
      },
    });
    c.pause();
    expect(paused).toBe(true);
    c.play();
    expect(paused).toBe(false);
    c.setRate(1.5);
    expect(rate).toBe(1.5);
    // Seek to source second 50 with a base of 40 -> element seek 10.
    c.seek(50);
    expect(seeks).toEqual([10]);
    expect(c.getPosition()).toBe(47);
    expect(c.isPaused()).toBe(false);
  });
});

describe("trackPlayerController", () => {
  it("forwards play/pause/seek/setRate to TrackPlayer (source-absolute)", async () => {
    const calls: string[] = [];
    const tp = {
      play: async () => {
        calls.push("play");
      },
      pause: async () => {
        calls.push("pause");
      },
      seekTo: async (s: number) => {
        calls.push(`seek:${s}`);
      },
      setRate: async (r: number) => {
        calls.push(`rate:${r}`);
      },
    };
    const c = trackPlayerController({
      trackPlayer: tp,
      getPosition: () => 12,
      getPaused: () => true,
    });
    await c.play();
    await c.pause();
    await c.seek(30);
    await c.setRate(2);
    expect(calls).toEqual(["play", "pause", "seek:30", "rate:2"]);
    expect(c.getPosition()).toBe(12);
    expect(c.isPaused()).toBe(true);
  });
});
