# F7FIVE0 design system v3

The source of truth is the F7FIVE0 Design System artifact in Claude. These files are exports of it for the code. Nothing in `frontend/` or `mobile/` uses them yet.

| File | For |
|---|---|
| `f7five0_tokens_v3.json` | Raw tokens (colors per theme, type, spacing, radius, shadow, size) |
| `f7five0_tokens_v3.css` | CSS custom properties plus type classes. Dark is the default; set `data-theme="light"` on `<html>` for light |
| `f7five0_tailwind-preset_v3.ts` | Tailwind preset mapping utilities to the CSS variables (`bg-surface-2`, `text-hive-text`, `shadow-hive`, `rounded-1`) |
| `f7five0_rn-theme_v3.ts` | React Native theme for mobile and TV (resolved colors, px numbers, Archivo font mapping) |
| `logos/` | `f7five0-wordmark.svg` (vector master, traced from the PSD) and `f7five0-wordmark.png` (raster fallback rendered from it) |

The red in the wordmark spells HIVE. In the UI it's the hidden layer: black and white carry every screen, and `hive` shows up once per view (the primary action, the active item, or the HIVE offset behind whatever has focus).

Font: Archivo from Google Fonts, weights 400 to 900.

Logo rule: the mark is only ever black and red, never reversed to white. On white or near-white grounds it sits bare. Anywhere else (every dark-theme placement, photos, backdrops) it sits in a white `logo-plate` box, square corners, padded a quarter of the logo's height.

Brand red is `#9C0404`, the PSD's exact red.

Icons are Lucide (ISC). Web: `lucide-react`. Mobile and TV: `lucide-react-native`. Draw them with a 2.25 stroke, square caps and miter joins; play, pause and skip are filled.

The square app mark is the honeycomb mark in `logos/`: `f7five0-mark.svg` (full comb), `f7five0-mark-cell.svg` (front cell, under 64 px), `f7five0-app-icon.svg` (iOS/PWA/apple-touch, white tile), `f7five0-adaptive-foreground.svg` (Android adaptive, background #FFFFFF), `f7five0-maskable.svg` (PWA maskable) and `f7five0-badge-mono.svg` (notification badge, one color by OS rule). The asset scripts (`mobile/scripts/gen-assets.js`, `frontend/scripts/generate-icons.mjs`) still draw arcHIVE's amber triangle; point them at these files next.
