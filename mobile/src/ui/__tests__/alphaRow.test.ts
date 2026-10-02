import { buildAlphaIndex, rowForItem } from "../alpha";

describe("rowForItem", () => {
  it("maps an item index to its grid row", () => {
    expect(rowForItem(0, 4)).toBe(0);
    expect(rowForItem(3, 4)).toBe(0);
    expect(rowForItem(4, 4)).toBe(1);
    expect(rowForItem(801, 4)).toBe(200);
    expect(rowForItem(7, 1)).toBe(7);
    expect(rowForItem(5, 0)).toBe(5);
  });

  it("jumps to the row holding a letter's first item", () => {
    const titles = ["Alien", "Avatar", "The Babadook", "Blade", "Casablanca", "Up"];
    const { firstIndex } = buildAlphaIndex(titles);
    expect(rowForItem(firstIndex.C, 4)).toBe(1);
    expect(rowForItem(firstIndex.B, 4)).toBe(0);
  });
});
