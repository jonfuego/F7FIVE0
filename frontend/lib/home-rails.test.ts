// node:test guard for the Home "Continue" rail on the web: it holds movies,
// shows, music videos and in-progress audio, so its title must not say
// "Watching" and its "See all" must not point at /movies.
//
// A source-text check on purpose: app/page.tsx is a client page with no
// pure helper to call, and the label is the whole behaviour.
//
// Run: node --test frontend/lib/home-rails.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("the Home page never calls the rail Continue Watching", () => {
  assert.ok(!page.includes("Continue Watching"));
});

test("the first rail is titled Continue and its See all is not /movies", () => {
  const row = /<Row\s+title="Continue"([^>]*)>/.exec(page);
  assert.ok(row, 'a <Row title="Continue"> exists');
  assert.ok(!/seeAllHref="\/movies"/.test(row[1]), "See all does not go to /movies");
  assert.ok(!/seeAllHref=/.test(row[1]), "a rail of mixed media has no single See all page");
});

test("the audio rail keeps its own title and its link to Music", () => {
  assert.match(page, /<Row title="Continue Listening" seeAllHref="\/music"/);
});

test("the PWA Continue shortcut is named Continue", () => {
  const manifest = JSON.parse(
    readFileSync(new URL("../public/manifest.json", import.meta.url), "utf8"),
  ) as { shortcuts: { name: string; url: string }[] };
  const sc = manifest.shortcuts.find((s) => s.url === "/?row=continue");
  assert.ok(sc, "a shortcut for /?row=continue exists");
  assert.equal(sc.name, "Continue");
});
