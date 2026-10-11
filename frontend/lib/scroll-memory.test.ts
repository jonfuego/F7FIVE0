// node:test coverage for remembering the scroll position on library pages.
//
// Run: node --test frontend/lib/scroll-memory.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  markRestore, pageKey, readPosition, RESTORE_LIMIT_MS, restoreStep, savePosition, takeRestore,
  type KeyValueStore,
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
