import { buildTrackArtwork } from "../artwork";

describe("signed art URL helper (buildTrackArtwork)", () => {
  const base = "https://api.example.com";

  it("prefers a signed absolute art URL from the API", () => {
    const signed = "https://api.example.com/api/art/album/abc/cover?uid=u1&exp=9999999999&sig=deadbeef";
    expect(buildTrackArtwork({ artUrl: signed, coverPath: "/api/art/album/abc/cover", base })).toBe(signed);
  });

  it("never hands a relative /api/art path to track-player (makes it absolute)", () => {
    const out = buildTrackArtwork({ coverPath: "/api/art/album/abc/cover", base });
    expect(out).toBe("https://api.example.com/api/art/album/abc/cover");
    expect(out?.startsWith("https://")).toBe(true);
  });

  it("passes through an already-absolute cover URL", () => {
    const remote = "https://image.tmdb.org/t/p/w500/x.jpg";
    expect(buildTrackArtwork({ coverPath: remote, base })).toBe(remote);
  });

  it("returns undefined when there is no art", () => {
    expect(buildTrackArtwork({ base })).toBeUndefined();
    expect(buildTrackArtwork({ artUrl: null, coverPath: null, base })).toBeUndefined();
  });
});
