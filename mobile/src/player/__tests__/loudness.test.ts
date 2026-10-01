import { dbToLinear, gainToVolumeMultiplier, pickGain, resolveVolume } from "../loudness";

describe("loudness leveling", () => {
  it("converts dB to a linear amplitude ratio", () => {
    expect(dbToLinear(0)).toBeCloseTo(1, 6);
    expect(dbToLinear(-6)).toBeCloseTo(0.5011872, 5);
    expect(dbToLinear(-20)).toBeCloseTo(0.1, 6);
    expect(dbToLinear(6)).toBeCloseTo(1.9952623, 5);
  });

  it("attenuates loud tracks (negative gain) toward the target", () => {
    // -6 dB -> ~0.501 multiplier.
    expect(gainToVolumeMultiplier(-6)).toBeCloseTo(0.5011872, 5);
    expect(gainToVolumeMultiplier(-20)).toBeCloseTo(0.1, 6);
  });

  it("leaves quiet tracks at full volume by default (attenuation only)", () => {
    // Positive gain would boost; default keeps it at unity (clip-safe).
    expect(gainToVolumeMultiplier(6)).toBe(1);
    expect(gainToVolumeMultiplier(3)).toBe(1);
    expect(gainToVolumeMultiplier(0)).toBe(1);
  });

  it("clamps a boosted multiplier to 1 even when boost is allowed", () => {
    // 0..1 device volume can't exceed unity.
    expect(gainToVolumeMultiplier(6, { allowBoost: true })).toBe(1);
    // Negative gain still attenuates with boost allowed.
    expect(gainToVolumeMultiplier(-6, { allowBoost: true })).toBeCloseTo(0.5011872, 5);
  });

  it("returns full volume for missing/invalid gain", () => {
    expect(gainToVolumeMultiplier(null)).toBe(1);
    expect(gainToVolumeMultiplier(undefined)).toBe(1);
    expect(gainToVolumeMultiplier(NaN)).toBe(1);
  });

  it("picks album vs track gain by mode", () => {
    const l = { track_gain_db: -8, album_gain_db: -5 };
    expect(pickGain(l, false)).toBe(-8);
    expect(pickGain(l, true)).toBe(-5);
    expect(pickGain(null, true)).toBeNull();
    // Falls back when the requested field is absent.
    expect(pickGain({ track_gain_db: -8 }, true)).toBe(-8);
    expect(pickGain({ album_gain_db: -5 }, false)).toBe(-5);
  });

  it("resolveVolume returns 1 when leveling is off", () => {
    const l = { track_gain_db: -12, album_gain_db: -10 };
    expect(resolveVolume(l, { enabled: false, albumMode: false, allowBoost: false })).toBe(1);
  });

  it("resolveVolume applies the mode-selected gain when enabled", () => {
    const l = { track_gain_db: -6, album_gain_db: -20 };
    expect(resolveVolume(l, { enabled: true, albumMode: false, allowBoost: false })).toBeCloseTo(0.5011872, 5);
    expect(resolveVolume(l, { enabled: true, albumMode: true, allowBoost: false })).toBeCloseTo(0.1, 6);
  });
});
