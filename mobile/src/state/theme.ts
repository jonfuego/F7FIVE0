/** F7FIVE0 dark theme tokens, ported from the PWA's globals.css :root. The
 * canonical background is #0b0604 (spec brand requirement). The web uses oklch;
 * these are the sRGB equivalents React Native can render.
 *
 * Token map from globals.css:
 *   --bg-hex  -> background        --bg-2/3/4 -> surface / surfaceAlt / surfaceHi
 *   --ink     -> text              --ink-2/3/4 -> textMuted / textFaint / ink4
 *   --line    -> line/border       --bulb     -> bulb (ivory accent)
 * The legacy amber `accent` is kept for the transport tint the player already
 * uses; `bulb` is the PWA's ivory accent for marquee/cards/progress. */
export const colors = {
  background: "#0b0604", // --bg-hex
  bg2: "#171210", // --bg-2
  bg3: "#211a15", // --bg-3
  bg4: "#2a221c", // --bg-4
  surface: "#171210",
  surfaceAlt: "#221a16",
  surfaceHi: "#2a221c",
  border: "#2e2420",
  line: "rgba(74,66,59,0.6)", // --line
  lineSoft: "rgba(74,66,59,0.3)", // --line-soft
  text: "#f7f2ea", // --ink
  ink2: "#d8d0c6", // --ink-2
  textMuted: "#a89f97", // --ink-3
  textFaint: "#6f665f", // --ink-4
  bulb: "#ece5d8", // --bulb (ivory accent, replaces amber on the web)
  bulb2: "#ddd6c8", // --bulb-2
  bulbGlow: "rgba(236,229,216,0.18)", // --bulb-glow
  accent: "#f59e0b",
  accentPressed: "#d97706",
  danger: "#ef4444",
  overlay: "rgba(0,0,0,0.6)",
} as const;

/** Font family names, matching the PWA's --display / --serif / --grotesk /
 * --mono stacks. The values are the expo-font keys loaded in src/state/fonts.ts
 * (BebasNeue_400Regular, Fraunces_*, Inter_*, JetBrainsMono_400Regular). */
export const fonts = {
  display: "BebasNeue_400Regular", // --display (marquee wordmark, big headings)
  serif: "Fraunces_600SemiBold", // --serif (taglines, about text)
  serifRegular: "Fraunces_400Regular",
  ui: "Inter_400Regular", // --grotesk (body/UI)
  uiMedium: "Inter_500Medium",
  uiSemiBold: "Inter_600SemiBold",
  uiBold: "Inter_700Bold",
  mono: "JetBrainsMono_400Regular", // --mono (meta lines, timestamps)
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
} as const;

/** Minimum touch target per the usability bar (44x44 dp). */
export const MIN_TOUCH = 44;

export const typography = {
  title: { fontSize: 28, fontWeight: "700" as const, color: colors.text },
  heading: { fontSize: 20, fontWeight: "700" as const, color: colors.text },
  body: { fontSize: 16, fontWeight: "400" as const, color: colors.text },
  label: { fontSize: 14, fontWeight: "600" as const, color: colors.textMuted },
  caption: { fontSize: 12, fontWeight: "400" as const, color: colors.textFaint },
} as const;
