import {
  BebasNeue_400Regular,
} from "@expo-google-fonts/bebas-neue";
import {
  Fraunces_400Regular,
  Fraunces_600SemiBold,
} from "@expo-google-fonts/fraunces";
import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
} from "@expo-google-fonts/inter";
import {
  JetBrainsMono_400Regular,
} from "@expo-google-fonts/jetbrains-mono";
import { useFonts } from "expo-font";

/** The four PWA type families, bundled with expo-font and pinned exact in
 * package.json (see globals.css --display / --serif / --grotesk / --mono).
 * Loaded once at the root; screens reference the family names via
 * `fonts` in src/state/theme.ts. */
export const APP_FONTS = {
  BebasNeue_400Regular,
  Fraunces_400Regular,
  Fraunces_600SemiBold,
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  JetBrainsMono_400Regular,
} as const;

/** Returns [loaded, error]. The root layout keeps the splash up until fonts
 * are ready so the marquee never flashes a fallback face. */
export function useAppFonts(): [boolean, Error | null] {
  const [loaded, error] = useFonts(APP_FONTS);
  return [loaded, error ?? null];
}
