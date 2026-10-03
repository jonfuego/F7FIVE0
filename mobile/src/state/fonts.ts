import {
  Archivo_400Regular,
  Archivo_500Medium,
  Archivo_600SemiBold,
  Archivo_700Bold,
  Archivo_800ExtraBold,
  Archivo_900Black,
} from "@expo-google-fonts/archivo";
import { useFonts } from "expo-font";

/** Archivo 400 to 900, bundled with expo-font and pinned exact in package.json.
 * The RN theme (src/state/f7five0-theme.ts) maps each weight to these keys via
 * fontFor(); src/state/theme.ts re-exports them under the fonts object. Loaded
 * once at the root so the UI never flashes a fallback face. */
export const APP_FONTS = {
  Archivo_400Regular,
  Archivo_500Medium,
  Archivo_600SemiBold,
  Archivo_700Bold,
  Archivo_800ExtraBold,
  Archivo_900Black,
} as const;

/** Returns [loaded, error]. The root layout keeps the splash up until fonts
 * are ready. */
export function useAppFonts(): [boolean, Error | null] {
  const [loaded, error] = useFonts(APP_FONTS);
  return [loaded, error ?? null];
}
