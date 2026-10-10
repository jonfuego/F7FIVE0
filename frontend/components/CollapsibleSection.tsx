// A collapsible Admin section card (item 5). The header row is a button that
// folds or unfolds the body; a chevron on the right shows the state. Collapsed,
// the header shows a one-line summary so the section is still useful folded.
//
// Collapsed state is remembered per user on the server through useViewPref
// (admin.collapsed) by the admin page, which passes `collapsed` and `onToggle`.
// A section that needs attention (a running or failed scan, an update available
// or running) stays open: `forceOpen` overrides the collapsed preference so a
// fold can never hide something that matters.

"use client";

import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Icon } from "@/components/Icon";

export function CollapsibleSection({
  id,
  title,
  collapsed,
  onToggle,
  summary,
  attention = false,
  forceOpen = false,
  children,
}: {
  id: string;
  title: string;
  collapsed: boolean;
  onToggle: (id: string) => void;
  summary?: string | null;
  attention?: boolean;
  forceOpen?: boolean;
  children: ReactNode;
}) {
  const open = !collapsed || forceOpen;
  const headingId = `admin-${id}-heading`;
  const bodyId = `admin-${id}-body`;

  return (
    <section
      className="rounded-xl border border-neutral-800 bg-neutral-900/40"
      aria-labelledby={headingId}
    >
      <button
        type="button"
        id={headingId}
        onClick={() => onToggle(id)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center gap-3 px-6 py-4 text-left"
      >
        <h2 className="text-base font-semibold">{title}</h2>
        {!open && summary ? (
          <span
            className={`truncate text-xs ${attention ? "text-amber-400" : "text-neutral-500"}`}
            data-testid={`admin-${id}-summary`}
          >
            {summary}
          </span>
        ) : null}
        {!open && attention && !summary ? (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" aria-hidden />
        ) : null}
        <Icon
          icon={ChevronDown}
          size={18}
          className={`ml-auto shrink-0 text-neutral-500 transition-transform ${open ? "" : "-rotate-90"}`}
        />
      </button>
      {open ? (
        <div id={bodyId} className="px-6 pb-6">
          {children}
        </div>
      ) : null}
    </section>
  );
}

export default CollapsibleSection;
