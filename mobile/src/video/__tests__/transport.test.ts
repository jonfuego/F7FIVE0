import {
  activeMarker,
  clampSeek,
  formatClock,
  hlsBaseOffset,
  resumePointFor,
  upNextState,
  UP_NEXT_COUNTDOWN_SEC,
} from "../transport";

const markers = [
  { kind: "intro", start_sec: 30, end_sec: 90 },
  { kind: "credits", start_sec: 1300, end_sec: 1400 },
];

describe("video transport", () => {
  it("hlsBaseOffset buckets HLS resume to 10 s and is 0 for direct play", () => {
    expect(hlsBaseOffset("hls", 127)).toBe(120);
    expect(hlsBaseOffset("hls", 0)).toBe(0);
    expect(hlsBaseOffset("direct", 127)).toBe(0);
  });

  it("clampSeek keeps back-10 / forward-30 inside the file", () => {
    expect(clampSeek(5 - 10, 100)).toBe(0);
    expect(clampSeek(90 + 30, 100)).toBe(100);
    expect(clampSeek(115, 100, 120)).toBe(120);
  });

  it("activeMarker finds the intro marker for Skip intro", () => {
    expect(activeMarker(45, markers)?.kind).toBe("intro");
    expect(activeMarker(95, markers)).toBeNull();
    expect(activeMarker(10, undefined)).toBeNull();
  });

  it("Up Next countdown starts at the credits marker and counts down", () => {
    expect(upNextState(1299, markers, true).show).toBe(false);
    const s = upNextState(1300, markers, true);
    expect(s.show).toBe(true);
    expect(s.secondsLeft).toBe(UP_NEXT_COUNTDOWN_SEC);
    expect(upNextState(1305.2, markers, true).secondsLeft).toBe(5);
    expect(upNextState(1320, markers, true).secondsLeft).toBe(0);
  });

  it("Up Next stays hidden without a next episode or a credits marker", () => {
    expect(upNextState(1350, markers, false).show).toBe(false);
    expect(upNextState(1350, [markers[0]], true).show).toBe(false);
  });

  it("formatClock renders m:ss and h:mm:ss", () => {
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(3723)).toBe("1:02:03");
  });
});

describe("resumePointFor", () => {
  it("resumes unfinished progress past 30 s and restarts finished items", () => {
    expect(resumePointFor({ position_sec: 600.7, duration_sec: 3000 })).toBe(600);
    expect(resumePointFor({ position_sec: 10, duration_sec: 3000 })).toBe(0);
    expect(resumePointFor({ position_sec: 2995, duration_sec: 3000 })).toBe(0);
    expect(resumePointFor({ position_sec: 600, completed_at: "2026-09-27T00:00:00Z" })).toBe(0);
    expect(resumePointFor(null)).toBe(0);
  });
});
