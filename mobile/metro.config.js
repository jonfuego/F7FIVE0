// Metro config. The key job here is TV variant resolution: when the TV target
// is being built (EXPO_TV=1, set by fixup-build.ps1 / prebuild), teach Metro to
// resolve `.tv.tsx` / `.tv.ts` / `.tv.jsx` / `.tv.js` variants BEFORE the plain
// ones. That lets a component or screen ship a TV-specific file (e.g.
// src/ui/MarqueeHeader.tv.tsx) that only lands in the TV bundle, so the TV
// APK's assets/index.android.bundle differs from the phone APK's.
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

if (process.env.EXPO_TV === "1") {
  config.resolver.sourceExts = [
    "tv.tsx",
    "tv.ts",
    "tv.jsx",
    "tv.js",
    ...config.resolver.sourceExts,
  ];
}

module.exports = config;
