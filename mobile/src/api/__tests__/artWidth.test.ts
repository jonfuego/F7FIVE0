import { artWidthFor, resolveArtUri, withArtWidth } from "../media";

jest.mock("@/state/config", () => ({ getApiBase: () => "http://srv:3001" }));

describe("art widths", () => {
  it("adds w after the v cache key", () => {
    expect(withArtWidth("http://s/api/art/movie/a/poster?v=9", 300)).toBe(
      "http://s/api/art/movie/a/poster?v=9&w=300",
    );
  });
  it("replaces an existing w", () => {
    expect(withArtWidth("http://s/api/art/x?v=1&w=600", 300)).toBe("http://s/api/art/x?v=1&w=300");
  });
  it("only sizes server art", () => {
    expect(resolveArtUri("/api/art/movie/a/poster?v=1", 300)).toBe(
      "http://srv:3001/api/art/movie/a/poster?v=1&w=300",
    );
    expect(resolveArtUri("https://image.tmdb.org/a.jpg", 300)).toBe("https://image.tmdb.org/a.jpg");
    expect(resolveArtUri("/api/art/movie/a/poster?v=1")).toBe("http://srv:3001/api/art/movie/a/poster?v=1");
  });
  it("picks 300 for small tiles and 600 for large", () => {
    expect(artWidthFor(44, 2.6)).toBe(300);
    expect(artWidthFor(140, 2.6)).toBe(600);
  });
});
