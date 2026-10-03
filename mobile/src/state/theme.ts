/** F7FIVE0 theme for mobile and TV, built on the design system v3 tokens in
 * ./f7five0-theme (a byte-identical copy of design/f7five0_rn-theme_v3.ts).
 *
 * Dark is the only theme this pass. The resolved v3 colors come from
 * f7five0-theme; this module keeps the legacy key names the screens already
 * import (background, surface, text, accent, ...) so the reskin stays a value
 * swap rather than a rename across every file. Black and white carry the UI;
 * the hive red is the single accent (primary action, active item, HIVE offset).
 */
import { colors as v3, fontFor, space, radius as v3radius, size } from "./f7five0-theme";

const d = v3.dark;

export const colors = {
  // Grounds and surfaces
  background: d.bg,
  bg2: d["surface-1"],
  bg3: d["surface-2"],
  bg4: d["surface-3"],
  surface: d["surface-1"],
  surfaceAlt: d["surface-2"],
  surfaceHi: d["surface-3"],
  // Lines
  border: d.line,
  line: d.line,
  lineSoft: d.line,
  lineStrong: d["line-strong"],
  // Ink
  text: d.ink,
  ink2: d["ink-2"],
  textMuted: d["ink-2"],
  textFaint: d["ink-3"],
  // Hive (the one accent). accent/accentPressed keep their old key names so the
  // player transport tint and every former accent callsite resolve to hive.
  accent: d.hive,
  accentPressed: d["hive-press"],
  hive: d.hive,
  hiveHover: d["hive-hover"],
  hivePress: d["hive-press"],
  hiveText: d["hive-text"],
  hiveTint: d["hive-tint"],
  hiveMark: d["hive-mark"],
  onHive: d["on-hive"],
  // Status and system
  focus: d.focus,
  positive: d.positive,
  warning: d.warning,
  danger: d.danger,
  logoPlate: d["logo-plate"],
  scrim: d.scrim,
  overlay: d.scrim,
} as const;

/** Archivo weights, mapped through f7five0-theme's fontFor(). The key names
 * match the old stacks so screens using fonts.display / fonts.ui / fonts.mono
 * keep working; every value is now an Archivo face. */
export const fonts = {
  display: fontFor(900),
  serif: fontFor(800),
  serifRegular: fontFor(400),
  ui: fontFor(400),
  uiMedium: fontFor(500),
  uiSemiBold: fontFor(600),
  uiBold: fontFor(700),
  mono: fontFor(400),
} as const;

export const spacing = {
  xs: space["1"],
  sm: space["2"],
  md: space["3"],
  lg: space["4"],
  xl: space["5"],
  xxl: space["6"],
} as const;

export const radius = {
  sm: v3radius["1"],
  md: v3radius["2"],
  lg: v3radius["2"],
  pill: v3radius.full,
} as const;

/** Minimum touch target per the usability bar (44x44 dp). */
export const MIN_TOUCH = size["tap-min"];

export const typography = {
  title: { fontSize: 28, fontWeight: "700" as const, color: colors.text },
  heading: { fontSize: 20, fontWeight: "700" as const, color: colors.text },
  body: { fontSize: 16, fontWeight: "400" as const, color: colors.text },
  label: { fontSize: 14, fontWeight: "600" as const, color: colors.textMuted },
  caption: { fontSize: 12, fontWeight: "400" as const, color: colors.textFaint },
} as const;
