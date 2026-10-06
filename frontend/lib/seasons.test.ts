// node:test coverage for TV season grouping and the season page route.
//
// Run: node --test frontend/lib/seasons.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { episodesForSeason, groupBySeason, parseSeasonParam, seasonHref, seasonTitle } from "./seasons.ts";

const eps = [
  { id: "s2e2", season_number: 2, episode_number: 2 },
  { id: "s1e2", season_number: 1, episode_number: 2 },
  { id: "sp1", season_number: 0, episode_number: 1 },
  { id: "s2e1", season_number: 2, episode_number: 1 },
  { id: "s1e1", season_number: 1, episode_number: 1 },
];

test("seasons ascend, episodes in order, Specials last", () => {
  const g = groupBySeason(eps);
  assert.deepEqual(g.map((x) => x.season), [1, 2, 0]);
  assert.deepEqual(g[0].episodes.map((e) => e.id), ["s1e1", "s1e2"]);
  assert.deepEqual(g[1].episodes.map((e) => e.id), ["s2e1", "s2e2"]);
});

test("a season page lists only that season's episodes", () => {
  assert.deepEqual(episodesForSeason(eps, 2).map((e) => e.id), ["s2e1", "s2e2"]);
  assert.deepEqual(episodesForSeason(eps, 3), []);
});

test("season links and titles", () => {
  assert.equal(seasonHref("f7f208ca", 2), "/series/f7f208ca/season/2");
  assert.equal(seasonTitle(0), "Specials");
  assert.equal(seasonTitle(4), "Season 4");
});

test("route segment parsing", () => {
  assert.equal(parseSeasonParam("2"), 2);
  assert.equal(parseSeasonParam("0"), 0);
  assert.equal(parseSeasonParam(["3"]), 3);
  assert.equal(parseSeasonParam("two"), null);
  assert.equal(parseSeasonParam("-1"), null);
  assert.equal(parseSeasonParam(undefined), null);
});
