# F7FIVE0 design system v1

The source of truth is the F7FIVE0 Design System artifact in Claude. These files are exports of it for the code. Nothing in `frontend/` or `mobile/` uses them yet.

| File | For |
|---|---|
| `f7five0_tokens_v1.json` | Raw tokens (colors per theme, type, spacing, radius, shadow, size) |
| `f7five0_tokens_v1.css` | CSS custom properties plus type classes. Dark is the default; set `data-theme="light"` on `<html>` for light |
| `f7five0_tailwind-preset_v1.ts` | Tailwind preset mapping utilities to the CSS variables (`bg-surface-2`, `text-hive-text`, `shadow-hive`, `rounded-1`) |
| `f7five0_rn-theme_v1.ts` | React Native theme for mobile and TV (resolved colors, px numbers, Archivo font mapping) |
| `logos/` | Wordmark: the original PNG, a transparent version for light grounds, a reversed version for dark grounds |

The red in the wordmark spells HIVE. In the UI it's the hidden layer: black and white carry every screen, and `hive` shows up once per view (the primary action, the active item, or the HIVE offset behind whatever has focus).

Font: Archivo from Google Fonts, weights 400 to 900.
