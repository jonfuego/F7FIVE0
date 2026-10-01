import { clampCrossfade, fadeInVolume, fadeOutVolume, shouldStartFade } from "../crossfade";
import { cleared, isElapsed, remainingSec, startEndOfTrack, startMinutes } from "../sleepTimer";

describe("crossfade fade scheduling", () => {
  it("clamps the crossfade setting to 0..10", () => {
    expect(clampCrossfade(-3)).toBe(0);
    expect(clampCrossfade(0)).toBe(0);
    expect(clampCrossfade(4.4)).toBe(4);
    expect(clampCrossfade(25)).toBe(10);
  });

  it("starts the fade only inside the crossfade window", () => {
    // 200s track, 6s crossfade -> fade starts at 194s.
    expect(shouldStartFade(190, 200, 6)).toBe(false);
    expect(shouldStartFade(195, 200, 6)).toBe(true);
    expect(shouldStartFade(100, 200, 0)).toBe(false); // off
    expect(shouldStartFade(100, 0, 6)).toBe(false); // unknown duration
  });

  it("ramps the outgoing volume 1 -> 0 across the window", () => {
    expect(fadeOutVolume(190, 200, 6)).toBe(1); // before window
    expect(fadeOutVolume(197, 200, 6)).toBeCloseTo(0.5, 5); // 3s remaining / 6
    expect(fadeOutVolume(200, 200, 6)).toBe(0); // end
    expect(fadeOutVolume(100, 200, 0)).toBe(1); // off -> full volume
  });

  it("ramps the incoming volume 0 -> 1 as the complement", () => {
    expect(fadeInVolume(0, 6)).toBe(0);
    expect(fadeInVolume(3, 6)).toBeCloseTo(0.5, 5);
    expect(fadeInVolume(6, 6)).toBe(1);
    expect(fadeInVolume(2, 0)).toBe(1); // off -> immediately full
  });
});

describe("sleep timer", () => {
  it("computes and expires a minutes timer", () => {
    const now = 1_000_000;
    const s = startMinutes(now, 30);
    expect(s.mode).toBe("minutes");
    expect(remainingSec(s, now)).toBe(1800);
    expect(isElapsed(s, now + 29 * 60_000)).toBe(false);
    expect(isElapsed(s, now + 30 * 60_000)).toBe(true);
    expect(remainingSec(s, now + 30 * 60_000)).toBe(0);
  });

  it("end-of-track and cleared timers never wall-clock-expire", () => {
    expect(isElapsed(startEndOfTrack(), 9_999_999)).toBe(false);
    expect(isElapsed(cleared(), 9_999_999)).toBe(false);
    expect(remainingSec(startEndOfTrack(), 0)).toBe(0);
  });
});
