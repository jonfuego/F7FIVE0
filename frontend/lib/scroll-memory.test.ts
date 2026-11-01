// node:test coverage for remembering the scroll position on library pages.
//
// Run: node --test frontend/lib/scroll-memory.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  backTarget, clearLeave, markRestore, pageKey, readPosition, recordLeave, RESTORE_LIMIT_MS,
  restoreStep, savePosition, shouldRestore, takeRestore, type KeyValueStore,
} from "./scroll-memory.ts";

function store(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  };
}

test("page key keeps the query", () => {
  assert.equal(pageKey("/search", "?q=a"), "/search?q=a");
  assert.notEqual(pageKey("/search", "?q=a"), pageKey("/search", "?q=b"));
});

test("a saved position is read back; zero or junk means none", () => {
  const s = store();
  savePosition(s, "/movies", 2400.4);
  assert.equal(readPosition(s, "/movies"), 2400);
  assert.equal(readPosition(s, "/music"), null);
  savePosition(s, "/music", 0);
  assert.equal(readPosition(s, "/music"), null);
  s.setItem("f7five0.scroll./tv", "abc");
  assert.equal(readPosition(s, "/tv"), null);
});

test("Back marks the page; the mark restores once, then a plain visit starts at the top", () => {
  const s = store();
  markRestore(s, "/movies");
  assert.equal(takeRestore(s, "/movies"), true);
  assert.equal(takeRestore(s, "/movies"), false);
});

test("a mark for another page does not restore this one, and is used up", () => {
  const s = store();
  markRestore(s, "/music");
  assert.equal(takeRestore(s, "/movies"), false);
  assert.equal(takeRestore(s, "/music"), false);
});

test("storage that throws never breaks the page", () => {
  const broken: KeyValueStore = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
    removeItem() { throw new Error("blocked"); },
  };
  markRestore(broken, "/movies");
  savePosition(broken, "/movies", 100);
  assert.equal(takeRestore(broken, "/movies"), false);
  assert.equal(readPosition(broken, "/movies"), null);
});

test("restore keeps trying while the list is still loading (page too short)", () => {
  // Placeholders only: the page cannot reach 2400 yet, scrollTo lands at 0.
  assert.equal(
    restoreStep({ target: 2400, scrollY: 0, maxScroll: 300, elapsedMs: 50, userScrolled: false }),
    "scroll",
  );
  // The tiles arrived and the scroll landed.
  assert.equal(
    restoreStep({ target: 2400, scrollY: 2400, maxScroll: 9000, elapsedMs: 400, userScrolled: false }),
    "done",
  );
});

test("restore stops when the user scrolls or the time limit passes", () => {
  assert.equal(
    restoreStep({ target: 2400, scrollY: 0, maxScroll: 300, elapsedMs: 50, userScrolled: true }),
    "give-up",
  );
  assert.equal(
    restoreStep({ target: 2400, scrollY: 300, maxScroll: 300, elapsedMs: RESTORE_LIMIT_MS, userScrolled: false }),
    "give-up",
  );
});

// W-06: the Back arrow on an artist opened from Songs went to "/music" (a fixed
// href), which redirected to Songs with the mark used up: top of the list.
test("the Back arrow goes back in history to the list the item was opened from", () => {
  const s = store();
  // Songs (history length 3) -> artist link pushes a 4th entry.
  recordLeave(s, "/music/songs", "/music/artists/7", 4);
  assert.equal(backTarget(s, "/music/artists/7", 4), "/music/songs");
  // Albums -> album the same way.
  recordLeave(s, "/music/albums", "/music/12", 5);
  assert.equal(backTarget(s, "/music/12", 5), "/music/albums");
});

test("the Back arrow uses its href when the list is not the page before this one", () => {
  const s = store();
  assert.equal(backTarget(s, "/movies/3", 2), null, "nothing recorded (direct link)");
  recordLeave(s, "/movies", "/movies/3", 2);
  assert.equal(backTarget(s, "/movies/4", 2), null, "a different item");
  // movies -> movie 3 -> (link) movie 5 -> (link) movie 3 again: history grew.
  assert.equal(backTarget(s, "/movies/3", 4), null, "same item pushed again later");
  clearLeave(s);
  assert.equal(backTarget(s, "/movies/3", 2), null, "cleared after use");
});

test("a redirect on the same URL or junk in storage records nothing", () => {
  const s = store();
  recordLeave(s, "/movies", "/movies", 2);
  assert.equal(backTarget(s, "/movies", 2), null);
  s.setItem("f7five0.scroll.leave", "{not json");
  assert.equal(backTarget(s, "/movies/3", 2), null);
  s.setItem("f7five0.scroll.leave", JSON.stringify({ from: 1, to: "/movies/3", len: 2 }));
  assert.equal(backTarget(s, "/movies/3", 2), null);
});

// W-06: browser Back sometimes did not restore (384 instead of 600): React
// renders a popstate navigation inside the popstate event, so the list mounted
// before the bubbling listener marked it.
test("a mount inside the popstate event restores even without the mark", () => {
  const s = store();
  assert.equal(shouldRestore(s, "/music/songs", "popstate"), true);
  assert.equal(shouldRestore(s, "/music/songs", "click"), false);
  assert.equal(shouldRestore(s, "/music/songs", undefined), false);
  markRestore(s, "/music/songs");
  assert.equal(shouldRestore(s, "/music/songs", undefined), true);
  assert.equal(shouldRestore(s, "/music/songs", undefined), false, "the mark is used once");
});
