import { applySortFilter, compareValues, titleSortKey, toggleDir, type FilterOption, type SortOption } from "../sortFilter";

interface Row {
  title: string;
  year: number | null;
  watched: boolean;
}

const rows: Row[] = [
  { title: "Banana", year: 2020, watched: false },
  { title: "apple", year: 1999, watched: true },
  { title: "Cherry", year: null, watched: false },
];

const sorts: SortOption<Row>[] = [
  { key: "title", label: "Title", value: (r) => r.title },
  { key: "year", label: "Year", value: (r) => r.year },
];

const filters: FilterOption<Row>[] = [
  { key: "watched", label: "Watched", predicate: (r) => r.watched },
  { key: "unwatched", label: "Unwatched", predicate: (r) => !r.watched },
];

describe("compareValues", () => {
  it("sorts strings case-insensitively and numbers numerically", () => {
    expect(compareValues("apple", "Banana")).toBeLessThan(0);
    expect(compareValues(1999, 2020)).toBeLessThan(0);
  });

  it("puts nulls last", () => {
    expect(compareValues(null, 5)).toBeGreaterThan(0);
    expect(compareValues(5, null)).toBeLessThan(0);
    expect(compareValues(null, null)).toBe(0);
  });
});

describe("applySortFilter", () => {
  it("sorts by title ascending (case-insensitive)", () => {
    const out = applySortFilter(rows, { sorts, sortKey: "title", dir: "asc" });
    expect(out.map((r) => r.title)).toEqual(["apple", "Banana", "Cherry"]);
  });

  it("sorts by year descending with nulls last", () => {
    const out = applySortFilter(rows, { sorts, sortKey: "year", dir: "desc" });
    expect(out.map((r) => r.year)).toEqual([2020, 1999, null]);
  });

  it("applies a filter before sorting", () => {
    const out = applySortFilter(rows, { sorts, filters, sortKey: "title", dir: "asc", filterKey: "unwatched" });
    expect(out.map((r) => r.title)).toEqual(["Banana", "Cherry"]);
  });

  it("does not mutate the input", () => {
    const copy = [...rows];
    applySortFilter(rows, { sorts, sortKey: "title", dir: "asc" });
    expect(rows).toEqual(copy);
  });

  it("is a no-op for unknown keys", () => {
    const out = applySortFilter(rows, { sorts, sortKey: "nope", dir: "asc", filterKey: "nope" });
    expect(out).toEqual(rows);
  });
});

describe("toggleDir", () => {
  it("flips direction", () => {
    expect(toggleDir("asc")).toBe("desc");
    expect(toggleDir("desc")).toBe("asc");
  });
});

describe("titleSortKey", () => {
  it("drops one leading article and lowercases, like the server", () => {
    expect(titleSortKey("The Abyss")).toBe("abyss");
    expect(titleSortKey("A Quiet Place")).toBe("quiet place");
    expect(titleSortKey("An American Werewolf in London")).toBe("american werewolf in london");
    expect(titleSortKey("THE 'Burbs")).toBe("'burbs");
    expect(titleSortKey("Theodore")).toBe("theodore");
    expect(titleSortKey("A.I. Artificial Intelligence")).toBe("a.i. artificial intelligence");
    expect(titleSortKey(null)).toBeNull();
  });

  it("uses the sort override when set", () => {
    expect(titleSortKey("The Abyss", "Zzz")).toBe("zzz");
    expect(titleSortKey("The Abyss", "  ")).toBe("abyss");
  });

  it("files The titles under their first real word in a Title sort", () => {
    type M = { title: string };
    const list: M[] = [{ title: "The Abyss" }, { title: "Accepted" }, { title: "Beetlejuice" }, { title: "The Burbs" }];
    const out = applySortFilter(list, {
      sorts: [{ key: "title", label: "Title", value: (m) => titleSortKey(m.title) }],
      sortKey: "title",
      dir: "asc",
    });
    expect(out.map((m) => m.title)).toEqual(["The Abyss", "Accepted", "Beetlejuice", "The Burbs"]);
  });
});
