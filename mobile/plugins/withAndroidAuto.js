/* Expo config plugin: declare Android Auto media support (crit 44).
 *
 * Adds:
 *  1. res/xml/automotive_app_desc.xml declaring a media <uses name="media"/>
 *     app, and
 *  2. the AndroidManifest <application> meta-data
 *     com.google.android.gms.car.application -> @xml/automotive_app_desc
 *
 * react-native-track-player 4.x's MusicService is NOT a media browser service,
 * so the car-facing MediaBrowserServiceCompat lives in the local Expo module
 * modules/f7five0-auto (F7FIVE0BrowserService, autolinked, manifest merged from
 * the module). JS serves the tree through src/player/AndroidAutoBridge.tsx
 * using the shape in src/player/browseTree.ts. This plugin adds the car
 * metadata + resource so the head unit lists the app.
 */
const { withAndroidManifest, withDangerousMod, AndroidConfig } = require("@expo/config-plugins");
const fs = require("fs");
const path = require("path");

const AUTOMOTIVE_DESC = `<?xml version="1.0" encoding="utf-8"?>
<automotiveApp>
    <uses name="media" />
</automotiveApp>
`;

function withAutomotiveResource(config) {
  return withDangerousMod(config, [
    "android",
    (cfg) => {
      const xmlDir = path.join(cfg.modRequest.platformProjectRoot, "app", "src", "main", "res", "xml");
      fs.mkdirSync(xmlDir, { recursive: true });
      fs.writeFileSync(path.join(xmlDir, "automotive_app_desc.xml"), AUTOMOTIVE_DESC);
      return cfg;
    },
  ]);
}

function withAutomotiveMetadata(config) {
  return withAndroidManifest(config, (cfg) => {
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(cfg.modResults);
    app["meta-data"] = app["meta-data"] || [];
    const NAME = "com.google.android.gms.car.application";
    if (!app["meta-data"].some((m) => m.$["android:name"] === NAME)) {
      app["meta-data"].push({
        $: { "android:name": NAME, "android:resource": "@xml/automotive_app_desc" },
      });
    }
    return cfg;
  });
}

module.exports = function withAndroidAuto(config) {
  config = withAutomotiveResource(config);
  config = withAutomotiveMetadata(config);
  return config;
};
