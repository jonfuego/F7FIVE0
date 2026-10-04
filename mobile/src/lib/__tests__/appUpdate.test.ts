import { formatSize, newerServerVersion } from "@/lib/appUpdate";

const info = (version: string) => ({
  available: true,
  version,
  url: "https://media.example.com/api/client/android-app/download?abi=arm64&uid=u&exp=1&sig=s",
});

describe("newerServerVersion", () => {
  it("offers a newer server build", () => {
    expect(newerServerVersion("1.0.0", info("1.1.0"))).toBe("1.1.0");
    expect(newerServerVersion("1.9.0", info("1.10.0"))).toBe("1.10.0");
  });

  it("never offers the same or an older build", () => {
    expect(newerServerVersion("1.1.0", info("1.1.0"))).toBeNull();
    expect(newerServerVersion("1.2.0", info("1.1.0"))).toBeNull();
  });

  it("ignores servers without an app or a link", () => {
    expect(newerServerVersion("1.0.0", { available: false })).toBeNull();
    expect(newerServerVersion("1.0.0", { available: true, version: "2.0.0" })).toBeNull();
    expect(newerServerVersion("1.0.0", null)).toBeNull();
  });
});

describe("formatSize", () => {
  it("rounds to MB", () => {
    expect(formatSize(34 * 1024 * 1024 + 10)).toBe("34 MB");
    expect(formatSize(1000)).toBe("1 MB");
    expect(formatSize(0)).toBe("");
    expect(formatSize(undefined)).toBe("");
  });
});
