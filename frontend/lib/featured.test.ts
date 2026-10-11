// node:test coverage for the Home hero featured pick and subtitle parts.
//
// Run: node --test frontend/lib/featured.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { heroSubtitleParts, pickFeatured, type FeaturedCandidate } from "./featured.ts";

function item(id: string, added: string, art: string | null): FeaturedCandidate {
  return {
    kind: "movie", id, title: id, subtitle: null, year: null,
    poster_path: art, added_at: added,
  };
}

test("prefers the newest item that has art", () => {
  const list = [
    item("new-noart", "2026-10-09T00:00:00Z", null),
    item("mid-art", "2026-10-08T00:00:00Z", "/a.jpg"),
    item("old-art", "2026-10-01T00:00:00Z", "/b.jpg"),
  ];
  assert.equal(pickFeatured(list)?.id, "mid-art");
});

test("falls back to the newest item when none have art", () => {
  const list = [
    item("old", "2026-10-01T00:00:00Z", null),
    item("new", "2026-10-09T00:00:00Z", null),
  ];
  assert.equal(pickFeatured(list)?.id, "new");
});

test("empty or null list has no pick", () => {
  assert.equal(pickFeatured([]), null);
  assert.equal(pickFeatured(null), null);
});

test("album subtitle links the artist and the type", () => {
  const parts = heroSubtitleParts(
    { kind: "album", year: 1976, subtitle: "AC/DC" }, "art-1",
  );
  assert.deepEqual(parts, [
    { text: "1976", href: null },
    { text: "AC/DC", href: "/music/artists/art-1" },
    { text: "Album", href: "/music/albums" },
  ]);
});

test("artist is plain text until the id is known; series and movie types link", () => {
  assert.equal(
    heroSubtitleParts({ kind: "album", year: null, subtitle: "X" }, null)[0].href,
    null,
  );
  assert.equal(
    heroSubtitleParts({ kind: "series", year: 2020, subtitle: null }, null).at(-1)?.href,
    "/series",
  );
  assert.equal(
    heroSubtitleParts({ kind: "movie", year: 2020, subtitle: null }, null).at(-1)?.href,
    "/movies",
  );
});
