import {
  castStartTime,
  castingLabel,
  isCasting,
  localResumePosition,
  receiverAbsPosition,
  shouldRecoverLocally,
} from "../castHandoff";

describe("isCasting / shouldRecoverLocally", () => {
  it("is casting only when connected and the hand-off succeeded", () => {
    expect(isCasting(true, true)).toBe(true);
    expect(isCasting(true, false)).toBe(false);
    expect(isCasting(false, true)).toBe(false);
    expect(isCasting(false, false)).toBe(false);
  });

  it("recovers locally only when not casting", () => {
    expect(shouldRecoverLocally(isCasting(true, true))).toBe(false);
    expect(shouldRecoverLocally(isCasting(true, false))).toBe(true);
    expect(shouldRecoverLocally(isCasting(false, false))).toBe(true);
  });
});

describe("castStartTime", () => {
  it("is absolute for direct play", () => {
    expect(castStartTime(754.9, "direct", 0)).toBe(754);
  });

  it("is relative to the HLS bucket", () => {
    expect(castStartTime(754, "hls", 750)).toBe(4);
    expect(castStartTime(750, "hls", 750)).toBe(0);
  });

  it("never goes negative and tolerates a missing offset", () => {
    expect(castStartTime(5, "hls", 750)).toBe(0);
    expect(castStartTime(120, "hls", null)).toBe(120);
    expect(castStartTime(0, "direct")).toBe(0);
  });
});

describe("receiverAbsPosition", () => {
  it("adds the HLS bucket back", () => {
    expect(receiverAbsPosition(60.4, "hls", 750)).toBe(810.4);
    expect(receiverAbsPosition(60.4, "direct", 750)).toBe(60.4);
  });

  it("is null when the receiver reported nothing usable", () => {
    expect(receiverAbsPosition(null, "hls", 750)).toBeNull();
    expect(receiverAbsPosition(undefined, "hls", 0)).toBeNull();
    expect(receiverAbsPosition(-1, "direct", 0)).toBeNull();
    expect(receiverAbsPosition(Number.NaN, "direct", 0)).toBeNull();
  });
});

describe("localResumePosition", () => {
  it("prefers the receiver's place", () => {
    expect(localResumePosition(900.7, 120, 7200)).toBe(900);
  });

  it("falls back to the phone's own position", () => {
    expect(localResumePosition(null, 120.9, 7200)).toBe(120);
    expect(localResumePosition(undefined, 120, 7200)).toBe(120);
    expect(localResumePosition(Number.NaN, 45, 7200)).toBe(45);
  });

  it("stays inside the movie and never goes negative", () => {
    expect(localResumePosition(9000, 0, 7200)).toBe(7200);
    expect(localResumePosition(null, -5, 7200)).toBe(0);
    expect(localResumePosition(0, 300, 7200)).toBe(0);
  });

  it("works with an unknown duration", () => {
    expect(localResumePosition(900, 10, null)).toBe(900);
  });
});

describe("castingLabel", () => {
  it("names the device", () => {
    expect(castingLabel("Living Room TV")).toBe("Casting to Living Room TV");
  });

  it("falls back without a name", () => {
    expect(castingLabel(null)).toBe("Casting");
    expect(castingLabel("  ")).toBe("Casting");
    expect(castingLabel()).toBe("Casting");
  });
});

// The wiring is in a screen with no pure seam, so these read the source: the
// local Video must not be mounted while casting, and error recovery must check
// the casting state before it calls loadUrl.
describe("VideoPlayer cast wiring", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { readFileSync } = require("fs") as typeof import("fs");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { join } = require("path") as typeof import("path");
  const source = readFileSync(join(__dirname, "..", "..", "video", "VideoPlayer.tsx"), "utf8");

  it("renders the local Video only when not casting", () => {
    expect(source).toMatch(/\{casting \? \([\s\S]*?\) : \(\s*<Video\b/);
  });

  it("checks the casting state before local error recovery", () => {
    const onError = source.slice(source.indexOf("const onError = useCallback"));
    const guard = onError.indexOf("shouldRecoverLocally(castingRef.current)");
    const reload = onError.indexOf("await loadUrl()");
    expect(guard).toBeGreaterThan(-1);
    expect(reload).toBeGreaterThan(guard);
  });

  it("asks the server for a cast stream and reads the receiver position on disconnect", () => {
    expect(source).toContain('purpose: "cast"');
    expect(source).toContain("receiverAbsPosition(lastReceiverPos.current");
    expect(source).toContain("localResumePosition(");
  });
});
