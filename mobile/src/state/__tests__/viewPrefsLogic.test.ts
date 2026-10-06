import { isViewKey, resolveViewPref, shouldPushLocal } from "../viewPrefsLogic";

describe("saved library views", () => {
  const isTab = (v: unknown): v is string => typeof v === "string" && ["all", "movies", "shows"].includes(v);

  it("the server's view wins (pick Shows on the web, open the app, still Shows)", () => {
    expect(resolveViewPref("shows", "movies", "all", isTab)).toBe("shows");
  });

  it("falls back to the local copy, then the default", () => {
    expect(resolveViewPref(undefined, "movies", "all", isTab)).toBe("movies");
    expect(resolveViewPref(undefined, undefined, "all", isTab)).toBe("all");
  });

  it("ignores values that aren't valid for the screen", () => {
    expect(resolveViewPref("playlists", "nope", "all", isTab)).toBe("all");
  });

  it("works for object views like sort state", () => {
    const sort = { sortKey: "year", dir: "desc", filterKey: null };
    expect(resolveViewPref(sort, undefined, { sortKey: "title", dir: "asc", filterKey: null })).toEqual(sort);
  });

  it("pushes a local-only choice up once", () => {
    expect(shouldPushLocal(undefined, "movies")).toBe(true);
    expect(shouldPushLocal("shows", "movies")).toBe(false);
    expect(shouldPushLocal(undefined, undefined)).toBe(false);
  });

  it("accepts the server's key format only", () => {
    expect(isViewKey("sort:movies")).toBe(true);
    expect(isViewKey("hub:video")).toBe(true);
    expect(isViewKey("Sort Movies")).toBe(false);
  });
});
