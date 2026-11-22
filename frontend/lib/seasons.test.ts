// node:test coverage for TV season grouping and the season page route.
//
// Run: node --test frontend/lib/seasons.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  episodesForSeason, groupBySeason, parseSeasonParam, seasonHref, seasonThumbs, seasonTitle,
} from "./seasons.ts";

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

test("season thumbs use the server list, season posters, show poster fallback", () => {
  const thumbs = seasonThumbs("abc", "/show.jpg", eps, [
    { season_number: 0, poster_path: "/sp.jpg", episode_count: 1 },
    { season_number: 2, poster_path: null, episode_count: 2 },
    { season_number: 1, poster_path: "/s1.jpg", episode_count: 1 },
  ]);
  assert.deepEqual(thumbs.map((t) => t.season), [1, 2, 0]);
  assert.deepEqual(thumbs.map((t) => t.poster), ["/s1.jpg", "/show.jpg", "/sp.jpg"]);
  assert.deepEqual(thumbs.map((t) => t.title), ["Season 1", "Season 2", "Specials"]);
  assert.deepEqual(thumbs.map((t) => t.countLabel), ["1 episode", "2 episodes", "1 episode"]);
  assert.equal(thumbs[0].href, "/series/abc/season/1");
});

test("season thumbs fall back to the episodes when the server sent no list", () => {
  const thumbs = seasonThumbs("abc", null, eps);
  assert.deepEqual(thumbs.map((t) => [t.season, t.episodeCount, t.poster]), [
    [1, 2, null], [2, 2, null], [0, 1, null],
  ]);
});
