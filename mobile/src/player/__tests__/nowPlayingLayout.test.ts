import { FIXED_ROWS_HEIGHT, SCREEN_PADDING, nowPlayingLayout } from "../nowPlayingLayout";

describe("nowPlayingLayout", () => {
  it("makes the artwork and controls big on a 411 x 914 phone", () => {
    const l = nowPlayingLayout(411, 914);
    expect(l.artwork).toBeGreaterThanOrEqual(340);
    expect(l.playDiameter).toBeGreaterThanOrEqual(80);
    expect(l.skipIcon).toBeGreaterThanOrEqual(44);
  });

  it("keeps the artwork inside the padding and the screen on a 360 x 640 phone", () => {
    const l = nowPlayingLayout(360, 640);
    expect(l.artwork).toBeLessThanOrEqual(360 - 2 * SCREEN_PADDING);
    expect(l.artwork + FIXED_ROWS_HEIGHT + l.playDiameter).toBeLessThanOrEqual(640);
  });

  it("never lets the artwork collapse on a very short window", () => {
    expect(nowPlayingLayout(360, 400).artwork).toBeGreaterThanOrEqual(120);
  });

  it("caps the controls on a tablet", () => {
    const l = nowPlayingLayout(1000, 1400);
    expect(l.playDiameter).toBeLessThanOrEqual(96);
    expect(l.skipIcon).toBeLessThanOrEqual(52);
    expect(l.secondaryIcon).toBeLessThanOrEqual(32);
    expect(l.artwork).toBeLessThanOrEqual(1000 - 2 * SCREEN_PADDING);
  });

  it("scales the play icon with the button", () => {
    const l = nowPlayingLayout(411, 914);
    expect(l.playIcon).toBeLessThan(l.playDiameter);
    expect(l.playIcon).toBeGreaterThan(l.playDiameter / 3);
  });
});
