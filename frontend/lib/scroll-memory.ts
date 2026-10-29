// Pure rules for remembering where you were on a library page (Movies, TV,
// Music, Music Videos, Home, Search). The React hook is lib/scroll-restoration.tsx;
// this file has no DOM access so node:test covers it (scroll-memory.test.ts).
//
// When a page restores:
//   - browser Back or Forward (popstate), or
//   - the in-app Back arrow (BackButton marks the page it is going to).
// A plain visit (top nav, a link) starts at the top, as before.
//
// The Back arrow goes back in history (router.back) when the page before this
// one is the list you came from: its href is a fixed parent ("/music" on an
// artist), which is not where you were when you came from Songs or Albums, and
// "/music" then redirects to the saved browse tab, which used up the mark. The
// list records the hop when it is left (recordLeave); BackButton checks it
// (backTarget) and falls back to its href (the old push) when it does not match.
//
// Browser Back: React renders a popstate navigation synchronously inside the
// popstate event, so the list can mount before a bubbling popstate listener
// runs. The mount therefore also counts window.event of type "popstate"
// (shouldRestore), and the listener is registered in the capture phase.
//
// Why the restore retries: the library pages render placeholders first and the
// tiles only after the list arrives, so on mount the page is too short and a
// single scrollTo(y) lands at 0. The hook keeps trying each frame until the
// page is tall enough, the user scrolls, or the time limit passes.

/** Storage the hook passes in (sessionStorage in the browser, a Map in tests). */
export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export const SCROLL_PREFIX = "f7five0.scroll.";
export const RESTORE_FLAG = "f7five0.scroll.restore";
/** The last list page left by a link: where the Back arrow can go back to. */
export const LEAVE_KEY = "f7five0.scroll.leave";
/** Give up on a restore after this long (a list that never gets tall enough). */
export const RESTORE_LIMIT_MS = 4000;

/** The page key: pathname plus query, so /search?q=a and ?q=b stay apart. */
export function pageKey(pathname: string, search: string): string {
  return `${pathname}${search}`;
}

/** Mark that the next mount of `key` should restore (Back arrow, popstate). */
export function markRestore(store: KeyValueStore, key: string): void {
  try {
    store.setItem(RESTORE_FLAG, key);
  } catch {
    // Storage can throw in private modes; the page then starts at the top.
  }
}

/** True once if `key` was marked; the mark is used up either way so a later
 * plain visit starts at the top. */
export function takeRestore(store: KeyValueStore, key: string): boolean {
  try {
    const marked = store.getItem(RESTORE_FLAG);
    if (marked === null) return false;
    store.removeItem(RESTORE_FLAG);
    return marked === key;
  } catch {
    return false;
  }
}

/** Restore on this mount: the page was marked (Back arrow, popstate listener)
 * or the mount is running inside the popstate event itself. Uses up the mark. */
export function shouldRestore(store: KeyValueStore, key: string, eventType: string | undefined): boolean {
  const marked = takeRestore(store, key);
  return marked || eventType === "popstate";
}

interface LeaveRecord {
  from: string;
  to: string;
  len: number;
}

/** A list page `from` was left for `to`; `historyLength` is history.length
 * after the new entry was pushed. Ignored when the URL did not change. */
export function recordLeave(store: KeyValueStore, from: string, to: string, historyLength: number): void {
  if (from === to) return;
  try {
    const rec: LeaveRecord = { from, to, len: historyLength };
    store.setItem(LEAVE_KEY, JSON.stringify(rec));
  } catch {
    // ignore
  }
}

export function clearLeave(store: KeyValueStore): void {
  try {
    store.removeItem(LEAVE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Where the Back arrow can go with history.back(), or null to use its href.
 * Only when this page is the one the list was left for and the history has
 * not grown since (a later push of the same URL must not go back to the page
 * in between).
 */
export function backTarget(store: KeyValueStore, current: string, historyLength: number): string | null {
  try {
    const raw = store.getItem(LEAVE_KEY);
    if (raw === null) return null;
    const rec = JSON.parse(raw) as Partial<LeaveRecord>;
    if (typeof rec.from !== "string" || typeof rec.to !== "string" || typeof rec.len !== "number") return null;
    if (rec.to !== current || rec.len !== historyLength || historyLength < 2) return null;
    return rec.from;
  } catch {
    return null;
  }
}

export function savePosition(store: KeyValueStore, key: string, y: number): void {
  if (!Number.isFinite(y) || y < 0) return;
  try {
    store.setItem(`${SCROLL_PREFIX}${key}`, String(Math.round(y)));
  } catch {
    // ignore
  }
}

export function readPosition(store: KeyValueStore, key: string): number | null {
  try {
    const raw = store.getItem(`${SCROLL_PREFIX}${key}`);
    if (raw === null) return null;
    const y = Number.parseInt(raw, 10);
    return Number.isFinite(y) && y > 0 ? y : null;
  } catch {
    return null;
  }
}

export type RestoreStep = "scroll" | "done" | "give-up";

/**
 * One frame of a restore.
 * - "done": the page is at the target (within 2 px).
 * - "scroll": try scrollTo(target) again (the page may still be growing).
 * - "give-up": the user scrolled, or the time limit passed.
 * `maxScroll` is how far the page can scroll right now
 * (document height minus the viewport).
 */
export function restoreStep(opts: {
  target: number;
  scrollY: number;
  maxScroll: number;
  elapsedMs: number;
  userScrolled: boolean;
}): RestoreStep {
  if (opts.userScrolled) return "give-up";
  if (Math.abs(opts.scrollY - opts.target) <= 2 && opts.maxScroll >= opts.target - 2) return "done";
  if (opts.elapsedMs >= RESTORE_LIMIT_MS) return "give-up";
  return "scroll";
}
