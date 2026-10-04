/* Expo config plugin: limit the native code an APK ships.
 *
 * F7FIVE0_ABIS (comma list, e.g. "arm64-v8a") is set by
 * scripts/release-apk.ps1 for official builds. Unset (dev builds, emulators)
 * keeps every ABI. Two places need it:
 *   - gradle.properties reactNativeArchitectures: what React Native and the
 *     autolinked native modules compile.
 *   - defaultConfig ndk.abiFilters: what gets packaged, including prebuilt
 *     .so files from dependencies, which reactNativeArchitectures alone does
 *     not strip.
 * The phone APK drops from about 78 MB (four ABIs) to one ABI's worth.
 */
const { withAppBuildGradle, withGradleProperties } = require("@expo/config-plugins");

const MARKER = "// f7five0: abiFilters";

function abis() {
  return (process.env.F7FIVE0_ABIS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

module.exports = function withAbiFilter(config) {
  const list = abis();
  if (!list.length) return config;

  config = withGradleProperties(config, (cfg) => {
    cfg.modResults = cfg.modResults.filter(
      (item) => !(item.type === "property" && item.key === "reactNativeArchitectures"),
    );
    cfg.modResults.push({ type: "property", key: "reactNativeArchitectures", value: list.join(",") });
    return cfg;
  });

  return withAppBuildGradle(config, (cfg) => {
    let src = cfg.modResults.contents;
    if (!src.includes(MARKER)) {
      const filters = list.map((a) => `"${a}"`).join(", ");
      const replaced = src.replace(
        /(defaultConfig\s*\{\s*\n)/,
        `$1        ${MARKER}\n        ndk { abiFilters ${filters} }\n`,
      );
      if (replaced === src) {
        throw new Error("withAbiFilter: defaultConfig block not found in app/build.gradle");
      }
      src = replaced;
    }
    cfg.modResults.contents = src;
    return cfg;
  });
};
