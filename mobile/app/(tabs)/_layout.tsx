// Route shell. The screen lives in src/screens/TabsLayout so Metro can swap in
// src/screens/TabsLayout.tv.tsx for the Android TV build (EXPO_TV=1, see
// metro.config.js). Phone and TV share this route path.
export { default } from "@/screens/TabsLayout";
