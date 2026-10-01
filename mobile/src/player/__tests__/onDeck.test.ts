import {
  deriveOnDeck,
  nextUnwatchedEpisode,
  sortEpisodes,
  type OnDeckEpisode,
  type ProgressMap,
} from "../onDeck";

function ep(id: string, s: number, e: number): OnDeckEpisode {
  return { id, season_number: s, episode_number: e, media_files: [{ id: `mf-${id}` }] };
}

describe("sortEpisodes", () => {
  it("orders by season then episode", () => {
    const out = sortEpisodes([ep("c", 2, 1), ep("a", 1, 1), ep("b", 1, 2)]);
    expect(out.map((e) => e.id)).toEqual(["a", "b", "c"]);
  });
});

describe("nextUnwatchedEpisode", () => {
  const eps = [ep("e1", 1, 1), ep("e2", 1, 2), ep("e3", 1, 3)];

  it("skips specials (season 0) when regular seasons exist", () => {
    expect(nextUnwatchedEpisode([ep("sp", 0, 1), ...eps], {})?.id).toBe("e1");
    expect(nextUnwatchedEpisode([ep("sp", 0, 1)], {})?.id).toBe("sp");
  });

  it("returns the first episode when nothing has been watched", () => {
    expect(nextUnwatchedEpisode(eps, {})?.id).toBe("e1");
  });

  it("returns the episode after the last completed one", () => {
    const progress: ProgressMap = {
      "mf-e1": { position_sec: 100, completed_at: "2026-01-01" },
    };
    expect(nextUnwatchedEpisode(eps, progress)?.id).toBe("e2");
  });

  it("prefers an in-progress episode (resume) over a later unstarted one", () => {
    const progress: ProgressMap = {
      "mf-e1": { position_sec: 100, completed_at: "2026-01-01" },
      "mf-e2": { position_sec: 300 }, // started, not completed
    };
    expect(nextUnwatchedEpisode(eps, progress)?.id).toBe("e2");
  });

  it("returns null when the whole series is completed", () => {
    const progress: ProgressMap = {
      "mf-e1": { position_sec: 1, completed_at: "x" },
      "mf-e2": { position_sec: 1, completed_at: "x" },
      "mf-e3": { position_sec: 1, completed_at: "x" },
    };
    expect(nextUnwatchedEpisode(eps, progress)).toBeNull();
  });

  it("returns null when there are no playable episodes", () => {
    expect(nextUnwatchedEpisode([{ id: "x", season_number: 1, episode_number: 1, media_files: [] }], {})).toBeNull();
    expect(nextUnwatchedEpisode([], {})).toBeNull();
  });

  it("handles unsorted input", () => {
    const shuffled = [ep("e3", 1, 3), ep("e1", 1, 1), ep("e2", 1, 2)];
    const progress: ProgressMap = { "mf-e1": { position_sec: 1, completed_at: "x" } };
    expect(nextUnwatchedEpisode(shuffled, progress)?.id).toBe("e2");
  });
});

describe("deriveOnDeck", () => {
  it("keeps episodic in-progress items and drops movies", () => {
    const items = [
      { kind: "episode", position_sec: 100, duration_sec: 1000 },
      { kind: "movie", position_sec: 100, duration_sec: 1000 },
      { kind: "series", position_sec: 0, duration_sec: 1000 },
    ];
    expect(deriveOnDeck(items).map((i) => i.kind)).toEqual(["episode", "series"]);
  });

  it("drops nearly-finished episodes", () => {
    const items = [
      { kind: "episode", position_sec: 990, duration_sec: 1000 }, // 99% -> drop
      { kind: "episode", position_sec: 500, duration_sec: 1000 }, // keep
    ];
    expect(deriveOnDeck(items)).toHaveLength(1);
    expect(deriveOnDeck(items)[0].position_sec).toBe(500);
  });

  it("keeps episodic items with unknown duration", () => {
    expect(deriveOnDeck([{ kind: "show", position_sec: 0 }])).toHaveLength(1);
  });
});
