/* Expo config plugin: let the app reach a plain-http F7FIVE0 server.
 *
 * Android blocks cleartext HTTP for apps that target API 28+ unless the
 * manifest allows it, and nothing else in the build did. So the release app
 * could not reach a LAN server at http://192.168.x.x:3001 (sign-in said
 * "Can't reach that server"), even though src/lib/serverUrl.ts defaults a
 * private address to http on purpose. The JS side already decides when http
 * is fine: private and loopback hosts by default, and a public host only after
 * the cleartext warning on the sign-in screen (isPublicCleartext).
 *
 * This sets android:usesCleartextTraffic="true" on <application>. One flag
 * covers fetch, react-native-video (ExoPlayer), track-player and images.
 */
const { withAndroidManifest, AndroidConfig } = require("@expo/config-plugins");

/** Mark the manifest's <application> as allowing cleartext. Idempotent. */
function allowCleartext(manifest) {
  const app = AndroidConfig.Manifest.getMainApplicationOrThrow(manifest);
  app.$ = app.$ || {};
  app.$["android:usesCleartextTraffic"] = "true";
  return manifest;
}

function withCleartext(config) {
  return withAndroidManifest(config, (cfg) => {
    cfg.modResults = allowCleartext(cfg.modResults);
    return cfg;
  });
}

module.exports = withCleartext;
module.exports.allowCleartext = allowCleartext;
