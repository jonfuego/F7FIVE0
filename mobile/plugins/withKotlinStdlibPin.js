/* Expo config plugin: pin kotlin-stdlib to the Expo SDK 51 / RN 0.74 Kotlin
 * line (1.9.x).
 *
 * react-native-passkey pulls androidx.credentials:1.3.0, which transitively
 * drags in kotlin-stdlib 2.1.0. The app is compiled with the Kotlin 1.9.0
 * compiler (Expo SDK 51 / react-native-tvos 0.74), which can only read Kotlin
 * metadata up to 2.0.0, so the 2.1.0 stdlib on the classpath fails the release
 * build ("Class 'kotlin.Unit' was compiled with an incompatible version of
 * Kotlin ... metadata 2.1.0 ... compiler 1.9.0"). Forcing kotlin-stdlib back to
 * 1.9.x resolves it; the stdlib is backward-compatible so androidx.credentials
 * still runs. prebuild --clean regenerates android/, so the force is injected
 * here rather than hand-edited into build.gradle.
 */
const { withProjectBuildGradle } = require("@expo/config-plugins");

const KOTLIN = "1.9.24";
const MARKER = "// f7five0: pin kotlin-stdlib";

const BLOCK = `
${MARKER}
allprojects {
    configurations.all {
        resolutionStrategy {
            force "org.jetbrains.kotlin:kotlin-stdlib:${KOTLIN}"
            force "org.jetbrains.kotlin:kotlin-stdlib-jdk8:${KOTLIN}"
            force "org.jetbrains.kotlin:kotlin-stdlib-jdk7:${KOTLIN}"
        }
    }
}
`;

module.exports = function withKotlinStdlibPin(config) {
  return withProjectBuildGradle(config, (cfg) => {
    if (cfg.modResults.language !== "groovy") return cfg;
    if (!cfg.modResults.contents.includes(MARKER)) {
      cfg.modResults.contents += `\n${BLOCK}\n`;
    }
    return cfg;
  });
};
