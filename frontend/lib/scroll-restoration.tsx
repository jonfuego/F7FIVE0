// Remember where you were on a library page (Movies, TV, Music, Music Videos,
// Home, Search) and put you back there when you come back with the browser's
// Back or the in-app Back arrow. A plain visit (top nav, a link) starts at the
// top. The rules are pure in lib/scroll-memory.ts (node:test covered).
//
// The position is saved on every scroll (once per frame) while the page is the
// current one, scoped by pathname + search. On a restore the hook retries
// scrollTo each frame until the page is tall enough: the library pages render
// placeholders first and the tiles only when the list arrives, so the old
// single scrollTo on mount landed at 0. It gives up when the user scrolls or
// after RESTORE_LIMIT_MS.
//
// When the page is left for another URL (a link to an item) it records the hop
// so the item's Back arrow can go back in history to exactly this page
// (backTarget in scroll-memory.ts); see markBackNavigation / backToList.
//
// Reads pathname/search from window.location instead of next/navigation hooks:
// useSearchParams forces every consumer page into a Suspense boundary. All
// window access is inside effects or event handlers, so SSR is safe.

"use client";

import { useEffect } from "react";
import {
  backTarget, clearLeave, markRestore, pageKey, readPosition, recordLeave, restoreStep,
  savePosition, shouldRestore, type KeyValueStore,
} from "@/lib/scroll-memory";

function sessionStore(): KeyValueStore | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function currentKey(): string {
  return pageKey(window.location.pathname, window.location.search);
}

// Browser Back / Forward: the URL has already changed when popstate fires, so
// mark the page being returned to. Registered once per tab, in the capture
// phase so it runs before the Next router's own (bubbling) popstate listener,
// which can render and mount the page synchronously. The mount also checks
// window.event (shouldRestore) in case this listener was not registered yet.
let popstateHooked = false;
export function hookPopstate(): void {
  if (typeof window === "undefined" || popstateHooked) return;
  popstateHooked = true;
  window.addEventListener(
    "popstate",
    () => {
      const store = sessionStore();
      if (store) markRestore(store, currentKey());
    },
    { capture: true },
  );
}

function currentEventType(): string | undefined {
  try {
    return window.event?.type;
  } catch {
    return undefined;
  }
}

/** Called by BackButton just before it navigates to `href` (no list to go
 * back to): mark `href` so it restores if it has a saved place. */
export function markBackNavigation(href: string): void {
  if (typeof window === "undefined") return;
  const store = sessionStore();
  if (!store) return;
  clearLeave(store);
  const url = new URL(href, window.location.origin);
  markRestore(store, pageKey(url.pathname, url.search));
}

/** Called by BackButton on click. When the page before this one in history is
 * the list it was opened from, marks that list, and returns true: the caller
 * then goes back in history instead of following its href. */
export function backToList(): boolean {
  if (typeof window === "undefined") return false;
  const store = sessionStore();
  if (!store) return false;
  const target = backTarget(store, currentKey(), window.history.length);
  if (target === null) return false;
  clearLeave(store);
  markRestore(store, target);
  return true;
}

export function useScrollRestoration(key?: string): void {
  useEffect(() => {
    hookPopstate();
    const store = sessionStore();
    if (!store) return;

    const here = currentKey();
    const storageKey = key ?? here;
    let restoring = false;
    let frame = 0;
    let saveQueued = false;
    let userScrolled = false;

    const onUserScroll = () => {
      userScrolled = true;
    };
    const userEvents = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    const stopWatchingUser = () => {
      for (const ev of userEvents) window.removeEventListener(ev, onUserScroll);
    };

    if (shouldRestore(store, here, currentEventType())) {
      const target = readPosition(store, storageKey);
      if (target !== null) {
        restoring = true;
        for (const ev of userEvents) window.addEventListener(ev, onUserScroll, { passive: true });
        const start = performance.now();
        const step = () => {
          const el = document.documentElement;
          const next = restoreStep({
            target,
            scrollY: window.scrollY,
            maxScroll: el.scrollHeight - window.innerHeight,
            elapsedMs: performance.now() - start,
            userScrolled,
          });
          if (next === "scroll") {
            window.scrollTo(0, target);
            frame = window.requestAnimationFrame(step);
            return;
          }
          restoring = false;
          stopWatchingUser();
        };
        frame = window.requestAnimationFrame(step);
      }
    }

    // Save once per frame while this page is the one in the address bar (a
    // navigation that already changed the URL must not overwrite it with the
    // next page's position) and no restore is still running.
    const onScroll = () => {
      if (saveQueued) return;
      saveQueued = true;
      window.requestAnimationFrame(() => {
        saveQueued = false;
        if (restoring || currentKey() !== here) return;
        savePosition(store, storageKey, window.scrollY);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      window.cancelAnimationFrame(frame);
      stopWatchingUser();
      window.removeEventListener("scroll", onScroll);
      const now = currentKey();
      if (now !== here) {
        // Left for another page (the URL is already the new one): remember the
        // hop for that page's Back arrow.
        recordLeave(store, here, now, window.history.length);
      } else if (restoring) {
        // Unmounted mid-restore on the same URL (a Suspense remount): keep
        // the mark so the next mount finishes the restore.
        markRestore(store, here);
      }
    };
  }, [key]);
}
