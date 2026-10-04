// ESLint flat config (ESLint 9, eslint-config-expo 10 for Expo SDK 54).
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    ignores: [
      "node_modules/",
      "android/",
      "ios/",
      "dist/",
      "reports/",
      "scripts/",
      "*.config.js",
    ],
  },
]);
