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
  // Expo SDK 54 is the last SDK with the old architecture. The app stays on it
  // until react-native-track-player and the other native libraries are moved
  // to New Architecture builds (SDK 55+ requires it).
  newArchEnabled: false,
  icon: "./assets/icon.png",
  userInterfaceStyle: "dark",
  backgroundColor: "#000000",
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#000000",
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
      backgroundColor: "#FFFFFF",
    },
    // Foreground service so react-native-track-player keeps audio alive when
    // the screen locks or the app backgrounds.
    permissions: [
      "INTERNET",
      "FOREGROUND_SERVICE",
      "FOREGROUND_SERVICE_MEDIA_PLAYBACK",
      "WAKE_LOCK",
      // Chromecast discovery: the Cast SDK finds receivers over mDNS, which
      // needs a Wi-Fi multicast lock. Without CHANGE_WIFI_MULTICAST_STATE the
      // device picker finds nothing and the cast button appears to do nothing.
      "ACCESS_WIFI_STATE",
      "CHANGE_WIFI_MULTICAST_STATE",
      "ACCESS_NETWORK_STATE",
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
        backgroundColor: "#000000",
        image: "./assets/splash.png",
        imageWidth: 200,
      },
    ],
    // Wire the release build to the F7FIVE0 release keystore (outside the repo).
    "./plugins/withAndroidReleaseSigning.js",
    // Official builds ship one ABI (F7FIVE0_ABIS, set by release-apk.ps1).
    "./plugins/withAbiFilter.js",
    // Android Auto media support (crit 44): automotive_app_desc + car metadata.
    "./plugins/withAndroidAuto.js",
    // Chromecast (phone only). Wires the react-native-google-cast options
    // provider + the Default Media Receiver (CC1AD845) into the Android
    // manifest. TV builds exclude it: react-native-google-cast is a phone/tablet
    // sender only, and the leanback TV build has no cast UI. Guarded on EXPO_TV
    // so the TV manifest never declares the options provider.
    ...(IS_TV
      ? []
      : [["./plugins/withGoogleCast.js", { receiverAppId: "CC1AD845" }] as [string, { receiverAppId: string }]]),
  ],
  experiments: {
    typedRoutes: false,
  },
});
