import { activeLyricIndex, hasLyrics, plainTextLines } from "../lyrics";

const lines = [
  { time_ms: 0, text: "one" },
  { time_ms: 5000, text: "two" },
  { time_ms: 10000, text: "three" },
];

describe("activeLyricIndex", () => {
  it("returns -1 before the first line", () => {
    expect(activeLyricIndex(lines, -1)).toBe(-1);
    // Exactly at the first line time counts as active.
    expect(activeLyricIndex(lines, 0)).toBe(0);
  });

  it("returns the last line at or before the position", () => {
    expect(activeLyricIndex(lines, 3000)).toBe(0);
    expect(activeLyricIndex(lines, 5000)).toBe(1);
    expect(activeLyricIndex(lines, 7000)).toBe(1);
    expect(activeLyricIndex(lines, 10000)).toBe(2);
    expect(activeLyricIndex(lines, 99999)).toBe(2);
  });

  it("handles empty/missing input", () => {
    expect(activeLyricIndex([], 1000)).toBe(-1);
    expect(activeLyricIndex(null, 1000)).toBe(-1);
    expect(activeLyricIndex(undefined, 1000)).toBe(-1);
  });
});

describe("plainTextLines", () => {
  it("splits text into lines, normalizing CRLF", () => {
    expect(plainTextLines("a\r\nb\nc")).toEqual(["a", "b", "c"]);
    expect(plainTextLines("")).toEqual([]);
    expect(plainTextLines(null)).toEqual([]);
  });
});

describe("hasLyrics", () => {
  it("is true for synced lines or non-empty text", () => {
    expect(hasLyrics({ lines, text: null })).toBe(true);
    expect(hasLyrics({ lines: null, text: "words" })).toBe(true);
    expect(hasLyrics({ lines: [], text: "   " })).toBe(false);
    expect(hasLyrics(null)).toBe(false);
  });
});
