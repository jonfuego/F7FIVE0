module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
    plugins: [
      // Reanimated's plugin must be listed last.
      "react-native-reanimated/plugin",
    ],
  };
};
