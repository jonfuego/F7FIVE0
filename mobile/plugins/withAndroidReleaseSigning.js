/* Expo config plugin: wire the release build to the F7FIVE0 release keystore.
 *
 * Reads keystore path + passwords from a properties file OUTSIDE the repo
 * (default ~/.f7five0-keys/keystore.properties, overridable via the
 * F7FIVE0_KEYSTORE_PROPERTIES env var). When the file is missing, release
 * builds keep React Native's default debug signing: fine for trying the app,
 * but sign real releases with your own key (see mobile/README.md). Because it runs on every
 * `expo prebuild`, the release signing survives `--clean` rebuilds (M6/M7)
 * without hand-editing android/app/build.gradle.
 */
const { withAppBuildGradle } = require("@expo/config-plugins");

const fs = require("fs");
const os = require("os");
const path = require("path");

const DEFAULT_PROPS = path.join(os.homedir(), ".f7five0-keys", "keystore.properties");

module.exports = function withAndroidReleaseSigning(config) {
  return withAppBuildGradle(config, (cfg) => {
    let src = cfg.modResults.contents;
    const propsPath = (process.env.F7FIVE0_KEYSTORE_PROPERTIES || DEFAULT_PROPS).replace(/\\/g, "/");

    if (!src.includes("signingConfigs.release")) {
      const releaseSigning = `        release {
            def mhProps = new Properties()
            def mhFile = new File("${propsPath}")
            if (mhFile.exists()) {
                mhFile.withInputStream { mhProps.load(it) }
                storeFile file(mhProps['storeFile'])
                storePassword mhProps['storePassword']
                keyAlias mhProps['keyAlias']
                keyPassword mhProps['keyPassword']
            }
        }
`;
      // Append the release signingConfig right after the debug block's closing
      // brace, staying inside the signingConfigs { } block.
      src = src.replace(
        /(keyPassword 'android'\s*\n\s*\}\n)/,
        `$1${releaseSigning}`,
      );
    }

    // Point the RELEASE buildType at the release signingConfig. Anchor on the
    // react-native signing comment that precedes it so we don't accidentally
    // rewrite the debug buildType's signingConfig line.
    if (fs.existsSync(propsPath)) {
      src = src.replace(
        /(signed-apk-android\.\s*\n\s*)signingConfig signingConfigs\.debug/,
        "$1signingConfig signingConfigs.release",
      );
    }

    cfg.modResults.contents = src;
    return cfg;
  });
};
