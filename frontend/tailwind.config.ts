import type { Config } from "tailwindcss";

// Surface the Marquee CSS variables to Tailwind so JSX can use the
// existing utility classes (text-ink, bg-bg-2, font-display, etc.) and
// stay consistent with the prototype's CSS class system in globals.css.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        "bg-2": "var(--bg-2)",
        "bg-3": "var(--bg-3)",
        "bg-4": "var(--bg-4)",
        line: "var(--line)",
        "line-soft": "var(--line-soft)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        "ink-4": "var(--ink-4)",
        bulb: "var(--bulb)",
        "bulb-2": "var(--bulb-2)",
        "bulb-glow": "var(--bulb-glow)",
      },
      fontFamily: {
        serif: "var(--serif)",
        display: "var(--display)",
        grotesk: "var(--grotesk)",
        mono: "var(--mono)",
      },
    },
  },
  plugins: [],
};

export default config;
