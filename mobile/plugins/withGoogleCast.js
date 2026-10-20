/* Expo config plugin: wire react-native-google-cast for the phone build.
 * Phone only; the TV build never adds this plugin (app.config.ts guards it on
 * EXPO_TV), so the TV manifest has no cast options provider.
 *
 * react-native-google-cast 4.x ships com.reactnative.googlecast.
 * GoogleCastOptionsProvider and reads the receiver id from the manifest
 * meta-data com.reactnative.googlecast.RECEIVER_APPLICATION_ID (defaulting to
 * the Default Media Receiver CC1AD845). The Cast SDK instantiates the
 * OPTIONS_PROVIDER class the first time CastContext.getSharedInstance runs
 * (at app startup via the cast hooks), so the class name MUST be exactly the
 * one the library ships or the app crashes on launch.
 *
 * Adds two <application> meta-data:
 *   com.google.android.gms.cast.framework.OPTIONS_PROVIDER_CLASS_NAME
 *     -> com.reactnative.googlecast.GoogleCastOptionsProvider
 *   com.reactnative.googlecast.RECEIVER_APPLICATION_ID -> CC1AD845
 *
 * Also pins the Cast SDK. react-native-google-cast asks for
 * play-services-cast-framework with the dynamic version "+" unless the root
 * project sets ext.castFrameworkVersion. On 2026-10-20 "+" moved from 22.3.1 to
 * 23.0.0, which pulls androidx.mediarouter 1.9.0-beta01 (needs compileSdk 37 and
 * Android Gradle plugin 9.1) and broke the release build. Every shipped APK up
 * to 1.0.16 was built with 22.3.1. Move the pin only together with the Expo SDK
 * upgrade (compileSdk and AGP).
 */
const {
  withAndroidManifest,
  withProjectBuildGradle,
  AndroidConfig,
} = require("@expo/config-plugins");

const CAST_FRAMEWORK_VERSION = "22.3.1";
const PIN_MARKER = "// f7five0: pin play-services-cast-framework";

const OPTIONS_PROVIDER_NAME =
  "com.google.android.gms.cast.framework.OPTIONS_PROVIDER_CLASS_NAME";
const OPTIONS_PROVIDER_CLASS = "com.reactnative.googlecast.GoogleCastOptionsProvider";
const RECEIVER_ID_NAME = "com.reactnative.googlecast.RECEIVER_APPLICATION_ID";
const DEFAULT_RECEIVER = "CC1AD845";

function setMeta(app, name, value) {
  app["meta-data"] = app["meta-data"] || [];
  const existing = app["meta-data"].find((m) => m.$["android:name"] === name);
  if (existing) {
    existing.$["android:value"] = value;
  } else {
    app["meta-data"].push({ $: { "android:name": name, "android:value": value } });
  }
}

/** Append the pin to the root build.gradle (once). The library reads it with
 * rootProject.ext, and the root script runs before the library's. */
function pinCastFramework(contents) {
  if (contents.includes(PIN_MARKER)) return contents;
  const lead = contents.endsWith("\n") ? "\n" : "\n\n";
  return `${contents}${lead}${PIN_MARKER}\next.castFrameworkVersion = "${CAST_FRAMEWORK_VERSION}"\n`;
}

module.exports = function withGoogleCast(config, props = {}) {
  const receiverAppId = props.receiverAppId || DEFAULT_RECEIVER;
  const withManifest = withAndroidManifest(config, (cfg) => {
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(cfg.modResults);
    setMeta(app, OPTIONS_PROVIDER_NAME, OPTIONS_PROVIDER_CLASS);
    setMeta(app, RECEIVER_ID_NAME, receiverAppId);
    return cfg;
  });
  return withProjectBuildGradle(withManifest, (cfg) => {
    cfg.modResults.contents = pinCastFramework(cfg.modResults.contents);
    return cfg;
  });
};

module.exports.pinCastFramework = pinCastFramework;
module.exports.CAST_FRAMEWORK_VERSION = CAST_FRAMEWORK_VERSION;
