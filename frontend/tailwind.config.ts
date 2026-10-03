import type { Config } from "tailwindcss";
import preset from "./tailwind.preset";

// The design system v3 utilities live in ./tailwind.preset (a byte-identical
// copy of design/f7five0_tailwind-preset_v3.ts). It maps Tailwind utilities
// to the CSS variables defined in app/f7five0-tokens.css. Keep the preset
// byte-identical to design/; put project-only settings (content globs) here.
const config: Config = {
  presets: [preset],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
};

export default config;
