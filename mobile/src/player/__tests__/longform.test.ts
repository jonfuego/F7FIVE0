import {
  PLAYED_FRACTION,
  PLAYED_TAIL_SEC,
  SKIP_BACK_SEC,
  SKIP_FORWARD_SEC,
  SPEEDS,
  chapterAt,
  clampSpeed,
  formatSpeed,
  isPlayed,
  skipBack,
  skipForward,
} from "../longform";

describe("long-form helpers", () => {
  it("skips back 15 s and forward 30 s", () => {
    expect(SKIP_BACK_SEC).toBe(15);
    expect(SKIP_FORWARD_SEC).toBe(30);
  });

  it("skip back stops at zero", () => {
    expect(skipBack(50)).toBe(35);
    expect(skipBack(10)).toBe(0);
  });

  it("skip forward stops at the end and runs free without a length", () => {
    expect(skipForward(10, 100)).toBe(40);
    expect(skipForward(80, 100)).toBe(100);
    expect(skipForward(10, null)).toBe(40);
    expect(skipForward(10, 0)).toBe(40);
  });

  it("is played within 30 s of the end or past 95 percent, whichever is first", () => {
    expect(PLAYED_TAIL_SEC).toBe(30);
    expect(PLAYED_FRACTION).toBe(0.95);
    expect(isPlayed(6839, 7200)).toBe(false);
    expect(isPlayed(6840, 7200)).toBe(true);
    expect(isPlayed(269, 300)).toBe(false);
    expect(isPlayed(270, 300)).toBe(true);
    expect(isPlayed(5000, 0)).toBe(false);
    expect(isPlayed(5000, null)).toBe(false);
  });

  it("finds the chapter at a time", () => {
    const ch = [
      { start_sec: 0, title: "A" },
      { start_sec: 60, title: "B" },
      { start_sec: 300, title: "C" },
    ];
    expect(chapterAt(ch, 59.9)).toBe(0);
    expect(chapterAt(ch, 60)).toBe(1);
    expect(chapterAt(ch, 9999)).toBe(2);
    expect(chapterAt([], 5)).toBe(-1);
    expect(chapterAt([{ start_sec: 30, title: "late" }], 10)).toBe(-1);
  });

  it("holds speed between 0.5 and 3", () => {
    expect(clampSpeed(0.25)).toBe(0.5);
    expect(clampSpeed(4)).toBe(3);
    expect(clampSpeed(1.25)).toBe(1.25);
    expect(clampSpeed(Number.NaN)).toBe(1);
    expect(SPEEDS[0]).toBe(0.5);
    expect(SPEEDS[SPEEDS.length - 1]).toBe(3);
    expect(formatSpeed(1)).toBe("1x");
    expect(formatSpeed(1.5)).toBe("1.5x");
  });
});
