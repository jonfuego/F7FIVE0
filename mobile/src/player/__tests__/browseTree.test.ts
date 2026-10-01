import { browseRoot, findRoot, ROOT_ID, rootChildren, sourceFor } from "../browseTree";

describe("Android Auto browse tree", () => {
  it("exposes the six spec categories in order", () => {
    expect(rootChildren().map((n) => n.id)).toEqual([
      "home",
      "recent",
      "mixes",
      "albums",
      "artists",
      "downloads",
    ]);
  });

  it("marks every root category browsable with a source", () => {
    for (const node of rootChildren()) {
      expect(node.browsable).toBe(true);
      expect(node.source).toBeDefined();
    }
  });

  it("has a browsable root", () => {
    expect(browseRoot()).toMatchObject({ id: ROOT_ID, browsable: true });
  });

  it("finds a root category by id and routes to its source", () => {
    expect(findRoot("albums")?.title).toBe("Albums");
    expect(sourceFor("albums")).toEqual({ kind: "albums" });
    expect(sourceFor("downloads")).toEqual({ kind: "downloads" });
  });

  it("returns null for the root parent and unknown ids", () => {
    expect(sourceFor(ROOT_ID)).toBeNull();
    expect(sourceFor("nope")).toBeNull();
    expect(findRoot("nope")).toBeNull();
  });
});

import { folderId, parseParent, parsePlayableId, playableId, songItems } from "../browseTree";

describe("Android Auto media ids", () => {
  it("round-trips playable ids that carry their list and position", () => {
    const id = playableId("album:abc", 3);
    expect(id).toBe("album:abc#3");
    expect(parsePlayableId(id)).toEqual({ listKey: "album:abc", index: 3 });
    expect(parsePlayableId("recent#0")).toEqual({ listKey: "recent", index: 0 });
    expect(parsePlayableId("no-index")).toBeNull();
    expect(parsePlayableId("x#-1")).toBeNull();
  });

  it("routes parent ids to categories and folders", () => {
    expect(parseParent("albums")).toEqual({ kind: "category", source: { kind: "albums" } });
    expect(parseParent(folderId.mix("most-played"))).toEqual({ kind: "mix", slug: "most-played" });
    expect(parseParent(folderId.album("a1"))).toEqual({ kind: "album", id: "a1" });
    expect(parseParent(folderId.artist("r1"))).toEqual({ kind: "artist", id: "r1" });
    expect(parseParent("nonsense")).toBeNull();
  });

  it("builds playable song items under a list key", () => {
    const items = songItems("mix:random", [
      { title: "A", artist_name: "X", album_title: "Y" },
      { title: "B" },
    ]);
    expect(items.map((i) => i.id)).toEqual(["mix:random#0", "mix:random#1"]);
    expect(items[0].subtitle).toBe("X · Y");
    expect(items[1].subtitle).toBeNull();
    expect(items.every((i) => !i.browsable)).toBe(true);
  });
});
