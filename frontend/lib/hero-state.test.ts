// node:test coverage for the Home hero state resolver.
//
// Run: node --test frontend/lib/hero-state.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveHeroState, heroEmptyMessage } from "./hero-state.ts";

test("a null list before the first load settles is loading", () => {
  assert.deepEqual(resolveHeroState(null, null), { type: "loading" });
});

test("a settled empty list is the empty state, not a skeleton", () => {
  assert.deepEqual(resolveHeroState([], null), { type: "empty" });
});

test("a settled list with items is ready", () => {
  assert.deepEqual(resolveHeroState([{ id: "m1" }], null), { type: "ready" });
});

test("a load error shows the message, even while the list is null", () => {
  assert.deepEqual(resolveHeroState(null, "boom"), {
    type: "error",
    message: "boom",
  });
});

test("a load error wins over a stale non-empty list", () => {
  assert.deepEqual(resolveHeroState([{ id: "m1" }], "boom"), {
    type: "error",
    message: "boom",
  });
});

test("admins get the Admin nudge, members get the plain line", () => {
  assert.equal(
    heroEmptyMessage(true),
    "Add library folders in Admin to get started",
  );
  assert.equal(heroEmptyMessage(false), "Nothing here yet");
});
