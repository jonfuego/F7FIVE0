// Route shell. The screen lives in src/screens/SearchScreen so Metro can swap in
// src/screens/SearchScreen.tv.tsx for the Android TV build (EXPO_TV=1, see
// metro.config.js). Phone and TV share this route path.
export { default } from "@/screens/SearchScreen";
