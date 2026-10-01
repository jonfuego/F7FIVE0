import { alphaBucket, buildAlphaIndex } from "../alpha";

describe("A-Z index builder", () => {
  it("buckets titles by first letter, ignoring leading articles", () => {
    expect(alphaBucket("Matrix")).toBe("M");
    expect(alphaBucket("The Matrix")).toBe("M");
    expect(alphaBucket("a Quiet Place")).toBe("Q");
    expect(alphaBucket("An Education")).toBe("E");
    expect(alphaBucket("  the Office")).toBe("O");
  });

  it("buckets digits and symbols under #", () => {
    expect(alphaBucket("1917")).toBe("#");
    expect(alphaBucket("!!!")).toBe("#");
    expect(alphaBucket("")).toBe("#");
  });

  it("builds the active-letter set and first-index map", () => {
    const { letters, firstIndex } = buildAlphaIndex(["Abba", "The Cars", "AC/DC", "1917"]);
    expect(letters.has("A")).toBe(true);
    expect(letters.has("C")).toBe(true); // "The Cars" -> C
    expect(letters.has("#")).toBe(true); // 1917
    expect(letters.has("B")).toBe(false);
    expect(firstIndex.A).toBe(0); // Abba is first A
    expect(firstIndex.C).toBe(1); // The Cars
    expect(firstIndex["#"]).toBe(3);
  });
});
