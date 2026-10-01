// Scroll position restoration for grid + home pages.
//
// Next.js App Router restores scroll inconsistently when a page route
// re-mounts on back navigation. This hook saves window.scrollY to
// sessionStorage on hide/unmount and restores it on mount, scoped by
// pathname + search so /search?q=foo and /search?q=bar stay distinct.
//
// Reads pathname/search directly from window.location instead of via
// next/navigation hooks: useSearchParams forces every consumer page to
// be wrapped in a Suspense boundary, and we don't need that here. The
// hook only fires inside useEffect (browser-only) so SSR is safe.

"use client";

import { useEffect } from "react";

const STORAGE_PREFIX = "f7five0.scroll.";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function useScrollRestoration(key?: string): void {
  useEffect(() => {
    if (!isBrowser()) return;

    const effectiveKey =
      key ??
      `${window.location.pathname}${window.location.search}`;
    const storageKey = `${STORAGE_PREFIX}${effectiveKey}`;

    // Restore. Two rAF ticks: the second handles late children that
    // pop in lazily and would otherwise reset scroll back to 0.
    const raw = window.sessionStorage.getItem(storageKey);
    if (raw !== null) {
      const parsed = Number.parseInt(raw, 10);
      if (Number.isFinite(parsed) && parsed >= 0) {
        const restore = () => {
          window.requestAnimationFrame(() => {
            window.scrollTo(0, parsed);
          });
        };
        window.requestAnimationFrame(restore);
      }
    }

    const save = () => {
      try {
        window.sessionStorage.setItem(storageKey, String(window.scrollY));
      } catch {
        // sessionStorage can throw in private mode; swallow.
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") save();
    };

    window.addEventListener("beforeunload", save);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      save();
      window.removeEventListener("beforeunload", save);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [key]);
}
