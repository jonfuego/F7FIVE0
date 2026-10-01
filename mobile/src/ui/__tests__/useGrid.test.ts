jest.mock("react-native", () => ({ useWindowDimensions: () => ({ width: 412, height: 915 }) }));
import { gridColumns, gridItemWidth } from "../useGrid";

describe("library grid geometry", () => {
  it("is 4 per row on a portrait phone, 6 in landscape, 7 on wide screens", () => {
    expect(gridColumns(412, 915)).toBe(4);
    expect(gridColumns(915, 412)).toBe(6);
    expect(gridColumns(1280, 800)).toBe(7);
  });

  it("fits 4 items plus gaps and the A-Z rail inside the screen", () => {
    const w = gridItemWidth(412, 4);
    expect(w).toBeGreaterThan(70);
    expect(w * 4 + 10 * 3 + 32 + 18).toBeLessThanOrEqual(412);
  });
});
