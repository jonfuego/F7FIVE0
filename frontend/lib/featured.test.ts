// node:test coverage for the Home hero featured pick, subtitle parts and facts line.
//
// Run: node --test frontend/lib/featured.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  heroFacts, heroSubtitleParts, pickFeatured, type FeaturedCandidate,
} from "./featured.ts";

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

test("movie facts: runtime, genres, rating", () => {
  assert.deepEqual(
    heroFacts("movie", {
      runtime_min: 108,
      genres: ["Action", "Science Fiction"],
      tmdb_rating: 7.94,
    }),
    ["1h 48m", "Action, Science Fiction", "★ 7.9"],
  );
});

test("movie facts keep the first three genres and trim blanks", () => {
  assert.deepEqual(
    heroFacts("movie", { genres: [" Drama ", "", "Crime", "Thriller", "War"] }),
    ["Drama, Crime, Thriller"],
  );
});

test("album facts: track count and total length", () => {
  assert.deepEqual(
    heroFacts("album", {
      tracks: [
        { duration_sec: 1800 },
        { duration_sec: 1500 },
        { duration_sec: 1500 },
      ],
      genres: ["Rock"],
    }),
    ["3 tracks", "1h 20m", "Rock"],
  );
  assert.deepEqual(heroFacts("album", { tracks: [{ duration_sec: 200 }] }), [
    "1 track",
    "3m",
  ]);
});

test("album total length is skipped when a track has no duration", () => {
  assert.deepEqual(
    heroFacts("album", {
      tracks: [{ duration_sec: 200 }, { duration_sec: null }],
    }),
    ["2 tracks"],
  );
});

test("series facts: seasons and episodes, specials not counted as a season", () => {
  assert.deepEqual(
    heroFacts("series", {
      episodes: [
        { season_number: 0 },
        { season_number: 1 },
        { season_number: 1 },
        { season_number: 2 },
      ],
      genres: ["Drama"],
      tmdb_rating: 8.4,
    }),
    ["2 seasons", "4 episodes", "Drama", "★ 8.4"],
  );
  assert.deepEqual(heroFacts("series", { episodes: [{ season_number: 1 }] }), [
    "1 season",
    "1 episode",
  ]);
});

test("missing fields are skipped, never blank or zero", () => {
  assert.deepEqual(heroFacts("movie", {}), []);
  assert.deepEqual(heroFacts("movie", null), []);
  assert.deepEqual(
    heroFacts("movie", { runtime_min: null, genres: [], tmdb_rating: null }),
    [],
  );
  assert.deepEqual(heroFacts("movie", { runtime_min: 0, tmdb_rating: 0 }), []);
  assert.deepEqual(heroFacts("movie", { runtime_min: 95 }), ["1h 35m"]);
  assert.deepEqual(heroFacts("series", { episodes: [] }), []);
  assert.deepEqual(heroFacts("album", { tracks: [], genres: null }), []);
  assert.deepEqual(heroFacts("series", { genres: ["Comedy"] }), ["Comedy"]);
});
