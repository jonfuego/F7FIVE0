import type { Config } from "tailwindcss";

// F7FIVE0 Tailwind preset v3. Values come from f7five0_tokens_v3.css (import it
// once in app/globals.css). Theme switches with data-theme="dark" | "light" on <html>.
// Usage in tailwind.config.ts: presets: [require("../design/f7five0_tailwind-preset_v3")]

const preset: Partial<Config> = {
  theme: {
    extend: {
      colors: {
        "bg": "var(--bg)",
        "surface-1": "var(--surface-1)",
        "surface-2": "var(--surface-2)",
        "surface-3": "var(--surface-3)",
        "line": "var(--line)",
        "line-strong": "var(--line-strong)",
        "ink": "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        "hive": "var(--hive)",
        "hive-hover": "var(--hive-hover)",
        "hive-press": "var(--hive-press)",
        "hive-text": "var(--hive-text)",
        "hive-tint": "var(--hive-tint)",
        "on-hive": "var(--on-hive)",
        "hive-mark": "var(--hive-mark)",
        "focus": "var(--focus)",
        "positive": "var(--positive)",
        "warning": "var(--warning)",
        "danger": "var(--danger)",
        "logo-plate": "var(--logo-plate)",
        "scrim": "var(--scrim)",
      },
      fontFamily: {
        display: "var(--font-display)",
        sans: "var(--font-sans)",
      },
      spacing: {
        "1": "var(--space-1)",
        "2": "var(--space-2)",
        "3": "var(--space-3)",
        "4": "var(--space-4)",
        "5": "var(--space-5)",
        "6": "var(--space-6)",
        "7": "var(--space-7)",
        "8": "var(--space-8)",
        "9": "var(--space-9)",
      },
      borderRadius: {
        "0": "var(--radius-0)",
        "1": "var(--radius-1)",
        "2": "var(--radius-2)",
        "full": "var(--radius-full)",
      },
      boxShadow: {
        hive: "var(--shadow-hive)",
        "hive-s": "var(--shadow-hive-s)",
        overlay: "var(--shadow-overlay)",
      },
      width: {
        "poster-s": "var(--poster-s)",
        "poster-m": "var(--poster-m)",
        "poster-l": "var(--poster-l)",
      },
      height: {
        topbar: "var(--topbar-h)",
        tabbar: "var(--tabbar-h)",
        miniplayer: "var(--miniplayer-h)",
      },
      minHeight: { tap: "var(--tap-min)" },
      minWidth: { tap: "var(--tap-min)" },
    },
  },
};

export default preset;
