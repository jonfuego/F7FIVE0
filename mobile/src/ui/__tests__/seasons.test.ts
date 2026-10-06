import { episodesForSeason, groupSeasons, parseSeason, seasonRoute, seasonTitle } from "../seasons";

describe("season grouping and route", () => {
  const eps = [
    { id: "s2e2", season_number: 2, episode_number: 2 },
    { id: "sp1", season_number: 0, episode_number: 1 },
    { id: "s1e1", season_number: 1, episode_number: 1 },
    { id: "s2e1", season_number: 2, episode_number: 1 },
  ];

  it("groups seasons ascending with Specials last", () => {
    expect(groupSeasons(eps).map(([n]) => n)).toEqual([1, 2, 0]);
  });

  it("lists only the season's episodes, in order", () => {
    expect(episodesForSeason(eps, 2).map((e) => e.id)).toEqual(["s2e1", "s2e2"]);
  });

  it("builds the season route and title", () => {
    expect(seasonRoute("abc", 2)).toBe("/movies/season/abc/2");
    expect(seasonTitle(0)).toBe("Specials");
    expect(seasonTitle(3)).toBe("Season 3");
  });

  it("parses the route param", () => {
    expect(parseSeason("2")).toBe(2);
    expect(parseSeason("x")).toBeNull();
    expect(parseSeason(undefined)).toBeNull();
  });
});
