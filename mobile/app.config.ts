import { ExpoConfig, ConfigContext } from "expo/config";

// EXPO_TV=1 switches the prebuild to the Android TV / tvOS targets (leanback
// launcher, TV manifest) via @react-native-tvos/config-tv. Phone builds leave
// it unset. Read it once here so the same config file drives both targets.
const IS_TV = process.env.EXPO_TV === "1";

// Optional default server baked into a build (EXPO_PUBLIC_API_BASE). Normally
// blank: users type their server address on the sign-in screen. The app talks
// to the same address people open in a browser; the web server forwards
// /api and /stream to the backends.
const API_BASE = process.env.EXPO_PUBLIC_API_BASE || "";

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "F7FIVE0",
  slug: "f7five0-app",
  scheme: "f7five0",
  version: "1.0.0",
  orientation: "default",
  icon: "./assets/icon.png",
  userInterfaceStyle: "dark",
  backgroundColor: "#0b0604",
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#0b0604",
  },
  assetBundlePatterns: ["**/*"],
  ios: {
    supportsTablet: true,
    bundleIdentifier: "com.f7five0.app",
    // Background audio for lock-screen playback (built later; declared now).
    infoPlist: {
      UIBackgroundModes: ["audio"],
    },
  },
  android: {
    package: "com.f7five0.app",
    // Bump with every sideloaded release so Android accepts it as an update.
    versionCode: 1,
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#0b0604",
    },
    // Foreground service so react-native-track-player keeps audio alive when
    // the screen locks or the app backgrounds.
    permissions: [
      "INTERNET",
      "FOREGROUND_SERVICE",
      "FOREGROUND_SERVICE_MEDIA_PLAYBACK",
      "WAKE_LOCK",
    ],
  },
  extra: {
    apiBase: API_BASE,
    isTv: IS_TV,
    router: {
      origin: false,
    },
  },
  plugins: [
    "expo-router",
    "expo-secure-store",
    "expo-font",
    "expo-asset",
    // TV config plugin. isTV is driven by the EXPO_TV env var at prebuild time.
    ["@react-native-tvos/config-tv", { isTV: IS_TV }],
    [
      "expo-splash-screen",
      {
        backgroundColor: "#0b0604",
        image: "./assets/splash.png",
        imageWidth: 200,
      },
    ],
    // Wire the release build to the F7FIVE0 release keystore (outside the repo).
    // Pin kotlin-stdlib to 1.9.x so androidx.credentials (pulled by
    // react-native-passkey) can't drag in a 2.1.0 stdlib the SDK 51 Kotlin
    // compiler can't read. Both builds need it (passkey is autolinked in both).
    "./plugins/withKotlinStdlibPin.js",
    "./plugins/withAndroidReleaseSigning.js",
    // Android Auto media support (crit 44): automotive_app_desc + car metadata.
    "./plugins/withAndroidAuto.js",
  ],
  experiments: {
    typedRoutes: false,
  },
});
