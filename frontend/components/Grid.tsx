// Library grid wall. CSS grid with auto-fill / minmax so tile count
// scales with viewport, keyed by the .grid-wall and .sq-grid styles in
// globals.css. Movies, Series → 2:3 grid-wall. Music, Music Videos →
// 1:1 sq-grid.

import type { ReactNode } from "react";

type Variant = "poster" | "square";

export function Grid({
  children,
  variant = "poster",
}: {
  children: ReactNode;
  variant?: Variant;
}) {
  return (
    <div className={variant === "square" ? "sq-grid" : "grid-wall"}>
      {children}
    </div>
  );
}

export function GridEmpty({ message }: { message: string }) {
  return (
    <div
      className="page-pad"
      style={{
        padding: "60px 64px 80px",
        textAlign: "center",
        color: "var(--ink-3)",
        fontFamily: "var(--serif)",
        fontVariationSettings: '"opsz" 144',
        fontSize: 22,
      }}
    >
      {message}
    </div>
  );
}
