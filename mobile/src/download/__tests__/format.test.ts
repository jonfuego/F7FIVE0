import { formatBytes, limitFraction } from "../format";

describe("formatBytes", () => {
  it("formats across units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5 MB");
    expect(formatBytes(2.5 * 1024 * 1024 * 1024)).toBe("2.5 GB");
  });

  it("handles invalid input", () => {
    expect(formatBytes(-1)).toBe("0 B");
    expect(formatBytes(NaN)).toBe("0 B");
  });
});

describe("limitFraction", () => {
  it("returns a clamped fraction, or null when unlimited", () => {
    expect(limitFraction(500, 1000)).toBe(0.5);
    expect(limitFraction(1500, 1000)).toBe(1);
    expect(limitFraction(500, 0)).toBeNull();
  });
});
