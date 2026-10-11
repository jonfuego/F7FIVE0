// A collapsible Admin section card (item 5). The header row is a button that
// folds or unfolds the body; a chevron on the right shows the state. Collapsed,
// the header shows a one-line summary so the section is still useful folded.
//
// Collapsed state is remembered per user on the server through useViewPref
// (admin.collapsed) by the admin page, which passes `collapsed` and `onToggle`.
// A section that needs attention (a running or failed scan, an update available
// or running) opens by itself: `forceOpen` overrides the saved fold so a fold
// does not hide something that matters. A click on the chevron still wins: it
// closes a forced-open section, and stays closed until attention newly appears.
// The rule lives in lib/collapsible.ts.

"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Icon } from "@/components/Icon";
import {
  choiceAfterClick,
  choiceAfterForceChange,
  isSectionOpen,
  storedNeedsToggle,
  type UserChoice,
} from "@/lib/collapsible";

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
  const [userChoice, setUserChoice] = useState<UserChoice>(null);
  const [prevForce, setPrevForce] = useState(forceOpen);
  // Attention that newly appears drops an earlier click (adjusted during render
  // so the section never paints in the stale state).
  if (prevForce !== forceOpen) {
    setPrevForce(forceOpen);
    setUserChoice(choiceAfterForceChange(prevForce, forceOpen, userChoice));
  }
  const open = isSectionOpen(collapsed, forceOpen, userChoice);

  function onClick() {
    const choice = choiceAfterClick(open);
    setUserChoice(choice);
    // Keep the saved fold in step with the click, but only flip it when it
    // differs (a forced-open section that was saved collapsed is already right).
    if (storedNeedsToggle(collapsed, choice === "open")) onToggle(id);
  }
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
        onClick={onClick}
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
