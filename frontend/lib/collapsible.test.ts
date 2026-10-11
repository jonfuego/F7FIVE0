// node:test coverage for the Admin section open/closed rule.
//
// Run: node --test frontend/lib/collapsible.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  choiceAfterClick,
  choiceAfterForceChange,
  isSectionOpen,
  storedNeedsToggle,
} from "./collapsible.ts";

test("no attention, no click: the saved fold state decides", () => {
  assert.equal(isSectionOpen(false, false, null), true);
  assert.equal(isSectionOpen(true, false, null), false);
});

test("attention set, no click: the section is open even if saved collapsed", () => {
  assert.equal(isSectionOpen(true, true, null), true);
  assert.equal(isSectionOpen(false, true, null), true);
});

test("attention set, user clicked collapse: the section is closed", () => {
  // Open because of attention; the click records "closed".
  const open = isSectionOpen(false, true, null);
  assert.equal(open, true);
  const choice = choiceAfterClick(open);
  assert.equal(choice, "closed");
  assert.equal(isSectionOpen(false, true, choice), false);
  // Same when the saved state was already collapsed (forced open on load).
  const open2 = isSectionOpen(true, true, null);
  assert.equal(isSectionOpen(true, true, choiceAfterClick(open2)), false);
});

test("a click can reopen a closed section, with or without attention", () => {
  assert.equal(choiceAfterClick(false), "open");
  assert.equal(isSectionOpen(true, false, "open"), true);
  assert.equal(isSectionOpen(true, true, "open"), true);
});

test("attention that stays set or clears keeps the click", () => {
  assert.equal(choiceAfterForceChange(true, true, "closed"), "closed");
  assert.equal(choiceAfterForceChange(true, false, "closed"), "closed");
  assert.equal(choiceAfterForceChange(false, false, "open"), "open");
});

test("attention newly appearing clears the click and opens the section", () => {
  const choice = choiceAfterForceChange(false, true, "closed");
  assert.equal(choice, null);
  assert.equal(isSectionOpen(true, true, choice), true);
  assert.equal(choiceAfterForceChange(false, true, null), null);
});

test("the saved fold state flips only when it differs from the user's choice", () => {
  // Saved open, user closes: flip to collapsed.
  assert.equal(storedNeedsToggle(false, false), true);
  // Saved collapsed, user opens: flip to open.
  assert.equal(storedNeedsToggle(true, true), true);
  // Saved collapsed, forced open, user closes: already collapsed, no flip.
  assert.equal(storedNeedsToggle(true, false), false);
  // Saved open, user opens (it was closed locally): already open, no flip.
  assert.equal(storedNeedsToggle(false, true), false);
});
