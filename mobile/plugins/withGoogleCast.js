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
 */
const { withAndroidManifest, AndroidConfig } = require("@expo/config-plugins");

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

module.exports = function withGoogleCast(config, props = {}) {
  const receiverAppId = props.receiverAppId || DEFAULT_RECEIVER;
  return withAndroidManifest(config, (cfg) => {
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(cfg.modResults);
    setMeta(app, OPTIONS_PROVIDER_NAME, OPTIONS_PROVIDER_CLASS);
    setMeta(app, RECEIVER_ID_NAME, receiverAppId);
    return cfg;
  });
};
