// The Android build must not float on play-services-cast-framework "+": on
// 2026-10-20 it moved to 23.0.0, which pulls androidx.mediarouter 1.9.0-beta01
// (compileSdk 37, AGP 9.1) and broke the release build. The config plugin pins it
// in the root build.gradle that `expo prebuild` regenerates.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const plugin = require("../../../plugins/withGoogleCast.js") as {
  pinCastFramework: (contents: string) => string;
  CAST_FRAMEWORK_VERSION: string;
};

describe("Cast SDK pin", () => {
  it("pins the version every shipped APK was built with", () => {
    expect(plugin.CAST_FRAMEWORK_VERSION).toBe("22.3.1");
  });

  it("appends ext.castFrameworkVersion to the root build.gradle", () => {
    const out = plugin.pinCastFramework("buildscript {}\n");
    expect(out).toContain('ext.castFrameworkVersion = "22.3.1"');
    expect(out.startsWith("buildscript {}\n")).toBe(true);
  });

  it("is idempotent", () => {
    const once = plugin.pinCastFramework("apply plugin: 'x'");
    expect(plugin.pinCastFramework(once)).toBe(once);
  });
});
