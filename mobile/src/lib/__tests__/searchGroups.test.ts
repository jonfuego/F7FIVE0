import { groupSearchResults } from "../searchGroups";

const row = (kind: string, id: string) => ({ kind, id, title: id });

describe("groupSearchResults", () => {
  it("puts artists first even when the API lists them last", () => {
    const groups = groupSearchResults([row("album", "al1"), row("song", "s1"), row("artist", "ar1")]);
    expect(groups[0].kind).toBe("artist");
    expect(groups[0].title).toBe("Artists");
  });

  it("orders the groups Artists, Albums, Songs", () => {
    const groups = groupSearchResults([row("song", "s1"), row("album", "al1"), row("artist", "ar1")]);
    expect(groups.map((g) => g.title)).toEqual(["Artists", "Albums", "Songs"]);
  });

  it("puts other kinds after Songs, in first-appearance order", () => {
    const groups = groupSearchResults([
      row("series", "sr1"),
      row("movie", "m1"),
      row("song", "s1"),
      row("album", "al1"),
      row("series", "sr2"),
      row("artist", "ar1"),
    ]);
    expect(groups.map((g) => g.kind)).toEqual(["artist", "album", "song", "series", "movie"]);
    expect(groups[3].title).toBe("Shows");
    expect(groups[4].title).toBe("Movies");
  });

  it("titles an unknown kind with a plain plural", () => {
    const groups = groupSearchResults([row("podcast", "p1")]);
    expect(groups[0].title).toBe("Podcasts");
  });

  it("hides empty groups", () => {
    const groups = groupSearchResults([row("album", "al1"), row("album", "al2")]);
    expect(groups.map((g) => g.kind)).toEqual(["album"]);
  });

  it("keeps the API order inside a group", () => {
    const groups = groupSearchResults([
      row("album", "b"),
      row("artist", "x"),
      row("album", "a"),
      row("artist", "w"),
      row("album", "c"),
    ]);
    expect(groups[0].data.map((r) => r.id)).toEqual(["x", "w"]);
    expect(groups[1].data.map((r) => r.id)).toEqual(["b", "a", "c"]);
  });

  it("returns no groups for nothing at all", () => {
    expect(groupSearchResults([])).toEqual([]);
    expect(groupSearchResults(undefined)).toEqual([]);
    expect(groupSearchResults(null)).toEqual([]);
  });
});
