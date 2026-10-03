// A horizontal cinema rail. Kicker (caps) + display title on the left,
// "All →" link on the right, doubled-up scroll-snap track of poster
// children below. Used on the home page exclusively; library pages use
// Grid instead.

import Link from "next/link";
import type { ReactNode } from "react";

type Props = {
  title: string;
  kicker?: string;
  seeAllHref?: string;
  children: ReactNode;
  emptyMessage?: string;
  isEmpty?: boolean;
  variant?: "default" | "continue";
};

export function Row({
  title,
  kicker,
  seeAllHref,
  children,
  isEmpty,
  emptyMessage,
  variant = "default",
}: Props) {
  return (
    <section className="rail">
      <div className="rail-head">
        <div className="titles">
          {kicker ? <div className="kicker">{kicker}</div> : null}
          <h2>{title}</h2>
        </div>
        {seeAllHref ? (
          <Link className="more" href={seeAllHref}>
            All →
          </Link>
        ) : null}
      </div>

      {isEmpty ? (
        <div
          className="page-pad"
          style={{
            padding: "16px 64px 32px",
            color: "var(--ink-3)",
            fontFamily: "var(--mono)",
            fontSize: 12,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
          }}
        >
          {emptyMessage ?? "Nothing here yet."}
        </div>
      ) : (
        <div className={`rail-track ${variant === "continue" ? "continue-rail" : ""}`}>
          {children}
        </div>
      )}
    </section>
  );
}

// In the new design the poster sets its own width via .poster, so RowItem
// is just a passthrough. Kept around so existing callers don't have to
// change shape.
export function RowItem({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
