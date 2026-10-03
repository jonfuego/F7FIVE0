// F7FIVE0 React Native theme v3 (mobile + TV). Generated from f7five0_tokens_v3.json.
// Fonts: load Archivo with @expo-google-fonts/archivo (pin 0.2.3 like the other @expo-google-fonts packages) and map the weights in fontFor().
// Icons: lucide-react-native with strokeWidth={2.25} strokeLinecap="square" strokeLinejoin="miter"; play/pause/skip filled.

export const colors = {
  dark: {
    "bg": "#000000",
    "surface-1": "#0e0e0e",
    "surface-2": "#181818",
    "surface-3": "#242424",
    "line": "#2c2c2c",
    "line-strong": "#777777",
    "ink": "#ffffff",
    "ink-2": "#c4c4c4",
    "ink-3": "#9a9a9a",
    "hive": "#9c0404",
    "hive-hover": "#b50808",
    "hive-press": "#820303",
    "hive-text": "#ff5c5e",
    "hive-tint": "#2b0a0a",
    "on-hive": "#ffffff",
    "hive-mark": "#ff5c5e",
    "focus": "#ffffff",
    "positive": "#5cc8ff",
    "warning": "#f2b33d",
    "danger": "#ff5c5e",
    "logo-plate": "#ffffff",
    "scrim": "rgba(0, 0, 0, 0.72)",
  },
  light: {
    "bg": "#ffffff",
    "surface-1": "#f4f4f4",
    "surface-2": "#eaeaea",
    "surface-3": "#dcdcdc",
    "line": "#d2d2d2",
    "line-strong": "#767676",
    "ink": "#000000",
    "ink-2": "#3a3a3a",
    "ink-3": "#595959",
    "hive": "#9c0404",
    "hive-hover": "#820303",
    "hive-press": "#6a0202",
    "hive-text": "#9c0404",
    "hive-tint": "#f8e6e6",
    "on-hive": "#ffffff",
    "hive-mark": "#9c0404",
    "focus": "#000000",
    "positive": "#005f9e",
    "warning": "#7f5100",
    "danger": "#9c0404",
    "logo-plate": "#ffffff",
    "scrim": "rgba(0, 0, 0, 0.56)",
  },
} as const;

export type ThemeName = keyof typeof colors;
export type ColorToken = keyof typeof colors.dark;

export const space = { "1": 4, "2": 8, "3": 12, "4": 16, "5": 24, "6": 32, "7": 48, "8": 64, "9": 96 } as const;
export const radius = { "0": 0, "1": 2, "2": 4, full: 9999 } as const;
export const size = { "poster-s": 112, "poster-m": 160, "poster-l": 220, "topbar-h": 64, "tabbar-h": 56, "miniplayer-h": 64, "tap-min": 44, "focus-w": 2 } as const;

// The HIVE offset. RN has no hard box-shadow on Android: render a hive-colored View
// behind the element, offset by this many px right and down.
// Logo: always the black and red PNG. On any ground other than white, wrap it in a
// View with backgroundColor colors[theme]["logo-plate"] and padding = logo height * 0.25.
export const logoPlatePadRatio = 0.25;

export const hiveOffset = { l: 6, s: 3 } as const;

const weights: Record<number, string> = {
  400: "Archivo_400Regular", 500: "Archivo_500Medium", 600: "Archivo_600SemiBold",
  700: "Archivo_700Bold", 800: "Archivo_800ExtraBold", 900: "Archivo_900Black",
};
export function fontFor(w: number): string { return weights[w] ?? weights[400]; }

export const type = {
  "display-xl": { fontFamily: fontFor(900), fontSize: 72, lineHeight: 68, letterSpacing: -1.44 },
  "display-l": { fontFamily: fontFor(900), fontSize: 48, lineHeight: 48, letterSpacing: -0.72 },
  "title-1": { fontFamily: fontFor(800), fontSize: 32, lineHeight: 36, letterSpacing: -0.32 },
  "title-2": { fontFamily: fontFor(800), fontSize: 22, lineHeight: 28 },
  "title-3": { fontFamily: fontFor(700), fontSize: 17, lineHeight: 22 },
  "body-l": { fontFamily: fontFor(400), fontSize: 17, lineHeight: 26 },
  "body": { fontFamily: fontFor(400), fontSize: 15, lineHeight: 22 },
  "body-strong": { fontFamily: fontFor(600), fontSize: 15, lineHeight: 22 },
  "caption": { fontFamily: fontFor(500), fontSize: 13, lineHeight: 18 },
  "overline": { fontFamily: fontFor(700), fontSize: 12, lineHeight: 16, letterSpacing: 1.44, textTransform: "uppercase" as const },
  "tv-hero": { fontFamily: fontFor(900), fontSize: 64, lineHeight: 64, letterSpacing: -1.28 },
  "tv-title": { fontFamily: fontFor(800), fontSize: 32, lineHeight: 40 },
  "tv-body": { fontFamily: fontFor(500), fontSize: 24, lineHeight: 32 },
} as const;
