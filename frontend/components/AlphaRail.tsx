// Vertical A-Z + # rail pinned to the right edge of the viewport.
// Scans the DOM for elements carrying `data-alpha-letter` and lets the
// user smooth-scroll to the first item whose letter matches. Letters
// with zero items are dimmed; the active letter is updated as the user
// scrolls based on the topmost visible item under the marquee.
//
// Usage: drop <AlphaRail /> inside the page (after the grid). Each
// grid item must carry `data-alpha-letter="A"` (uppercase A-Z, or `#`
// for non-alpha leading chars) and `data-alpha-anchor="<n>"` where n is
// the item's index within its sibling list. The rail does not own the
// data; it just observes the DOM, so it stays decoupled from the data
// shape on each page.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const LETTERS: readonly string[] = [
  "#",
  "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
  "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
];

// Distance from the top of the viewport that "first visible item" must
// be measured from. The marquee sticky header is roughly 60px tall; we
// add a little breathing room.
const TOP_OFFSET = 88;

export function AlphaRail({
  containerSelector,
  resetKey,
}: {
  /** Optional CSS selector to scope the scan; defaults to the document. */
  containerSelector?: string;
  /** Bump this when the underlying list changes (filter switch, new
   *  fetch) so the rail re-scans for available letters. */
  resetKey?: string | number;
}) {
  const [available, setAvailable] = useState<Set<string>>(() => new Set());
  const [active, setActive] = useState<string | null>(null);
  const rafRef = useRef<number | null>(null);

  const root = useCallback((): ParentNode => {
    if (!containerSelector) return document;
    return document.querySelector(containerSelector) ?? document;
  }, [containerSelector]);

  // Discover which letters have at least one matching item.
  useEffect(() => {
    const scan = () => {
      const items = root().querySelectorAll<HTMLElement>("[data-alpha-letter]");
      const seen = new Set<string>();
      items.forEach((el) => {
        const v = el.dataset.alphaLetter;
        if (v) seen.add(v);
      });
      setAvailable(seen);
    };
    scan();
    // Re-scan after a tick so that React has flushed any pending children.
    const t = window.setTimeout(scan, 50);
    return () => window.clearTimeout(t);
  }, [root, resetKey]);

  // Track the active letter as the user scrolls.
  useEffect(() => {
    const onScroll = () => {
      if (rafRef.current !== null) return;
      rafRef.current = window.requestAnimationFrame(() => {
        rafRef.current = null;
        const items = root().querySelectorAll<HTMLElement>("[data-alpha-letter]");
        for (const el of Array.from(items)) {
          const rect = el.getBoundingClientRect();
          if (rect.bottom >= TOP_OFFSET) {
            setActive(el.dataset.alphaLetter ?? null);
            return;
          }
        }
        setActive(null);
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [root, resetKey, available]);

  const jumpTo = useCallback(
    (letter: string) => {
      if (!available.has(letter)) return;
      const target = root().querySelector<HTMLElement>(
        `[data-alpha-letter="${cssEscape(letter)}"]`,
      );
      if (!target) return;
      const rect = target.getBoundingClientRect();
      const absoluteTop = rect.top + window.scrollY - TOP_OFFSET;
      window.scrollTo({ top: absoluteTop, behavior: "smooth" });
      // Optimistic active highlight; the scroll listener catches up once
      // the smooth-scroll resolves.
      setActive(letter);
    },
    [available, root],
  );

  return (
    <nav className="alpha-rail" aria-label="Jump to letter">
      {LETTERS.map((letter) => {
        const enabled = available.has(letter);
        const isActive = active === letter;
        return (
          <button
            key={letter}
            type="button"
            className={`alpha-rail-letter${enabled ? "" : " is-disabled"}${
              isActive ? " is-active" : ""
            }`}
            onClick={() => jumpTo(letter)}
            disabled={!enabled}
            aria-label={`Jump to ${letter === "#" ? "numbers and symbols" : letter}`}
          >
            {letter}
          </button>
        );
      })}
    </nav>
  );
}

// CSS.escape isn't universally available in older runtimes; provide a
// minimal fallback that handles `#` and the alphabet (the only inputs
// we ever pass).
function cssEscape(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/[^a-zA-Z0-9]/g, (ch) => `\\${ch}`);
}

/** Helper for grid items: derives the rail letter from a title string. */
export function alphaLetterOf(title: string | null | undefined): string {
  if (!title) return "#";
  // Strip leading articles per common library convention.
  const stripped = title.trim().replace(/^(?:the|a|an)\s+/i, "");
  const first = stripped.charAt(0).toUpperCase();
  if (first >= "A" && first <= "Z") return first;
  return "#";
}
