import { episodeStateLabel, filterEpisodes, progressFraction } from "../podcastState";

describe("podcast episode state", () => {
  it("words the state", () => {
    expect(episodeStateLabel({ kind: "new" }, 3600)).toBe("New");
    expect(episodeStateLabel({ kind: "played" }, 3600)).toBe("Played");
    expect(episodeStateLabel({ kind: "in_progress", position_sec: 600 }, 3600)).toBe("50 min left");
    expect(episodeStateLabel({ kind: "in_progress", position_sec: 3590 }, 3600)).toBe("1 min left");
    expect(episodeStateLabel({ kind: "in_progress", position_sec: 600 }, 5400)).toBe("1 hr 20 min left");
    expect(episodeStateLabel({ kind: "in_progress", position_sec: 600 }, null)).toBe("Resume at 10:00");
  });

  it("measures progress between 0 and 1", () => {
    expect(progressFraction({ kind: "in_progress", position_sec: 900 }, 3600)).toBe(0.25);
    expect(progressFraction({ kind: "in_progress", position_sec: 9000 }, 3600)).toBe(1);
    expect(progressFraction({ kind: "new" }, 3600)).toBe(0);
    expect(progressFraction({ kind: "played" }, 3600)).toBe(1);
  });

  it("filters a show's episodes: unplayed and downloaded", () => {
    const eps = [
      { id: "a", state: { kind: "new" } as const },
      { id: "b", state: { kind: "played" } as const },
      { id: "c", state: { kind: "in_progress", position_sec: 5 } as const },
    ];
    const downloaded = (id: string) => id === "b";
    expect(filterEpisodes(eps, "all", downloaded).map((e) => e.id)).toEqual(["a", "b", "c"]);
    expect(filterEpisodes(eps, "unplayed", downloaded).map((e) => e.id)).toEqual(["a", "c"]);
    expect(filterEpisodes(eps, "downloaded", downloaded).map((e) => e.id)).toEqual(["b"]);
  });
});
