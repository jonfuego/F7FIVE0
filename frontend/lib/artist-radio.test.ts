// node:test coverage for the shared artist radio starter.
//
// Run: node --test frontend/lib/artist-radio.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { artistRadioPath, startArtistRadio } from "./artist-radio.ts";

test("path targets the artist-radio auto-playlist and encodes the id", () => {
  assert.equal(
    artistRadioPath("abc-123"),
    "/api/library/auto-playlist/artist-radio/abc-123",
  );
  assert.equal(
    artistRadioPath("a/b c"),
    "/api/library/auto-playlist/artist-radio/a%2Fb%20c",
  );
});

test("hands the fetched items to playNextBlock", async () => {
  const paths: string[] = [];
  const played: string[][] = [];
  const ok = await startArtistRadio<string>("ar1", {
    get: async (p) => {
      paths.push(p);
      return { items: ["t1", "t2"] };
    },
    playNextBlock: (items) => played.push(items),
  });
  assert.equal(ok, true);
  assert.deepEqual(paths, ["/api/library/auto-playlist/artist-radio/ar1"]);
  assert.deepEqual(played, [["t1", "t2"]]);
});

test("no artist id starts nothing and does not fetch", async () => {
  let fetched = false;
  const ok = await startArtistRadio<string>(null, {
    get: async () => {
      fetched = true;
      return { items: ["t1"] };
    },
    playNextBlock: () => assert.fail("should not play"),
  });
  assert.equal(ok, false);
  assert.equal(fetched, false);
});

test("empty or malformed answers start nothing", async () => {
  for (const answer of [{ items: [] }, {}, null, undefined]) {
    const ok = await startArtistRadio<string>("ar1", {
      get: async () => answer,
      playNextBlock: () => assert.fail("should not play"),
    });
    assert.equal(ok, false);
  }
});

test("a failed fetch is swallowed", async () => {
  const ok = await startArtistRadio<string>("ar1", {
    get: async () => {
      throw new Error("boom");
    },
    playNextBlock: () => assert.fail("should not play"),
  });
  assert.equal(ok, false);
});
