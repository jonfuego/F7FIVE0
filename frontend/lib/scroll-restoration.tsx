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
// Reads pathname/search from window.location instead of next/navigation hooks:
// useSearchParams forces every consumer page into a Suspense boundary. All
// window access is inside effects or event handlers, so SSR is safe.

"use client";

import { useEffect } from "react";
import {
  markRestore, pageKey, readPosition, restoreStep, savePosition, takeRestore,
  type KeyValueStore,
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
// mark the page being returned to. Registered once per tab.
let popstateHooked = false;
function hookPopstate(): void {
  if (popstateHooked) return;
  popstateHooked = true;
  window.addEventListener("popstate", () => {
    const store = sessionStore();
    if (store) markRestore(store, currentKey());
  });
}

/** Called by BackButton just before it navigates to `href`. */
export function markBackNavigation(href: string): void {
  if (typeof window === "undefined") return;
  const store = sessionStore();
  if (!store) return;
  const url = new URL(href, window.location.origin);
  markRestore(store, pageKey(url.pathname, url.search));
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

    if (takeRestore(store, here)) {
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
    };
  }, [key]);
}
