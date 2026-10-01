// Shared frame for authenticated pages. Wraps children with the Marquee
// top bar (sticky theatre header) and the page content. The persistent
// dock (MiniPlayer) is mounted globally in app/layout.tsx so it survives
// route changes; this shell only owns the header.
//
// Keyboard: the ⌘K / Ctrl+K useEffect listener that navigates to /search
// lives inside MarqueeTop ((metaKey || ctrlKey) && key === 'k'), so any
// page that renders this AuthShell gets the global shortcut for free.
// Esc handling for modal overlays is owned by each modal's own listener.
//
// Login does NOT use this shell. The middleware lets /login through
// unauthenticated, and the login page renders its own centered card.

import type { ReactNode } from "react";
import { MarqueeTop } from "./MarqueeTop";

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <MarqueeTop />
      <main className="flex-1">{children}</main>
    </div>
  );
}
