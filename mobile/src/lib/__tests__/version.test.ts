import {
  compareVersion,
  isUpdateRequired,
  isUpdateRequiredForPlatform,
  MinClientVersions,
} from "../version";

describe("min-version comparison", () => {
  it("compares equal versions as 0", () => {
    expect(compareVersion("1.2.3", "1.2.3")).toBe(0);
    expect(compareVersion("1.2", "1.2.0")).toBe(0);
  });

  it("orders lower versions as -1 and higher as 1", () => {
    expect(compareVersion("1.0.0", "1.0.1")).toBe(-1);
    expect(compareVersion("1.2.0", "1.10.0")).toBe(-1);
    expect(compareVersion("2.0.0", "1.9.9")).toBe(1);
  });

  it("treats missing components as zero", () => {
    expect(compareVersion("1", "1.0.0")).toBe(0);
    expect(compareVersion("1.0", "1.0.1")).toBe(-1);
  });

  it("isUpdateRequired is true only when strictly below the floor", () => {
    expect(isUpdateRequired("1.0.0", "1.1.0")).toBe(true);
    expect(isUpdateRequired("1.1.0", "1.1.0")).toBe(false);
    expect(isUpdateRequired("1.2.0", "1.1.0")).toBe(false);
  });

  it("resolves the floor per platform", () => {
    const mins: MinClientVersions = {
      android: "1.5.0",
      ios: "0.0.0",
      android_tv: "2.0.0",
      tvos: "0.0.0",
    };
    expect(isUpdateRequiredForPlatform("1.0.0", "android", mins)).toBe(true);
    expect(isUpdateRequiredForPlatform("1.5.0", "android", mins)).toBe(false);
    expect(isUpdateRequiredForPlatform("1.0.0", "android_tv", mins)).toBe(true);
    expect(isUpdateRequiredForPlatform("9.9.9", "ios", mins)).toBe(false);
  });
});
