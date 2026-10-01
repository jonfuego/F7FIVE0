import { bucketPeaks, isBarPlayed, peakToHeight } from "../waveform";

describe("bucketPeaks", () => {
  it("passes through when shorter than or equal to buckets", () => {
    expect(bucketPeaks([1, 2, 3], 4)).toEqual([1, 2, 3]);
    expect(bucketPeaks([1, 2, 3, 4], 4)).toEqual([1, 2, 3, 4]);
  });

  it("averages into the requested number of buckets", () => {
    // 8 values -> 2 buckets: mean of first 4 and last 4.
    expect(bucketPeaks([0, 0, 0, 0, 100, 100, 100, 100], 2)).toEqual([0, 100]);
    expect(bucketPeaks([10, 20, 30, 40], 2)).toEqual([15, 35]);
  });

  it("handles empty / zero buckets", () => {
    expect(bucketPeaks([], 64)).toEqual([]);
    expect(bucketPeaks([1, 2, 3], 0)).toEqual([]);
  });
});

describe("isBarPlayed", () => {
  it("marks bars up to the played fraction", () => {
    // 4 bars: centers at 0.125, 0.375, 0.625, 0.875.
    expect(isBarPlayed(0, 4, 0.5)).toBe(true);
    expect(isBarPlayed(1, 4, 0.5)).toBe(true);
    expect(isBarPlayed(2, 4, 0.5)).toBe(false);
    expect(isBarPlayed(3, 4, 0.5)).toBe(false);
    expect(isBarPlayed(0, 0, 0.5)).toBe(false);
  });
});

describe("peakToHeight", () => {
  it("maps 0..100 into the min..max range and clamps", () => {
    expect(peakToHeight(0, 2, 40)).toBe(2);
    expect(peakToHeight(100, 2, 40)).toBe(40);
    expect(peakToHeight(50, 2, 42)).toBe(22);
    expect(peakToHeight(-5, 2, 40)).toBe(2); // clamp low
    expect(peakToHeight(200, 2, 40)).toBe(40); // clamp high
    expect(peakToHeight(NaN, 2, 40)).toBe(2);
  });
});
