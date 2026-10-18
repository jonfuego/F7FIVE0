import {
  kindShowsNames,
  kindsWithMultipleLibraries,
  librariesForKind,
  libraryNavEntries,
  type LibraryInfo,
} from "../libraryNav";

const LIBS: LibraryInfo[] = [
  { id: "m1", name: "Movies", kind: "movies", sort_order: 0 },
  { id: "m2", name: "Kids Movies", kind: "movies", sort_order: 1 },
  { id: "tv1", name: "TV", kind: "tv", sort_order: 0 },
  { id: "mu1", name: "Music", kind: "music", sort_order: 0 },
];

describe("library-aware sub-nav", () => {
  it("shows names only when a kind has more than one library", () => {
    expect(kindShowsNames(LIBS, "movies")).toBe(true);
    expect(kindShowsNames(LIBS, "tv")).toBe(false);
    expect(kindShowsNames(LIBS, "music")).toBe(false);
    expect(kindShowsNames(LIBS, "podcasts")).toBe(false);
  });

  it("lists nav entries only for a multi-library kind, ordered by sort_order", () => {
    expect(libraryNavEntries(LIBS, "tv")).toEqual([]);
    const movies = libraryNavEntries(LIBS, "movies");
    expect(movies.map((e) => e.id)).toEqual(["m1", "m2"]);
  });

  it("sorts by sort_order then name", () => {
    const mixed: LibraryInfo[] = [
      { id: "b", name: "Bravo", kind: "movies", sort_order: 1 },
      { id: "a", name: "Alpha", kind: "movies", sort_order: 1 },
      { id: "z", name: "Zero", kind: "movies", sort_order: 0 },
    ];
    expect(librariesForKind(mixed, "movies").map((l) => l.id)).toEqual(["z", "a", "b"]);
  });

  it("kindsWithMultipleLibraries lists only multi-library kinds", () => {
    expect(kindsWithMultipleLibraries(LIBS)).toEqual(["movies"]);
  });
});
