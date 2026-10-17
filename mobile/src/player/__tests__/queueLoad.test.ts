import { loadQueueInStages, type QueueLoadDeps } from "../queueLoad";

interface Item {
  id: string;
  playable?: boolean;
}

/** A fake player: records calls in order and keeps the queue like TrackPlayer would. */
function harness(items: Item[], tappedIndex: number) {
  const log: string[] = [];
  const queue: string[] = [];
  let current = true;
  const deps: QueueLoadDeps<Item, string> = {
    items,
    tappedIndex,
    sign: async (item) => {
      log.push(`sign:${item.id}`);
      return item.playable === false ? null : item.id;
    },
    reset: async () => {
      log.push("reset");
      queue.length = 0;
    },
    add: async (entries, insertAt) => {
      log.push(`add:${entries.join(",")}@${insertAt ?? "end"}`);
      if (insertAt === undefined) queue.push(...entries);
      else queue.splice(insertAt, 0, ...entries);
    },
    skip: async (i) => {
      log.push(`skip:${i}`);
    },
    play: async () => {
      log.push("play");
    },
    isCurrent: () => current,
  };
  return {
    deps,
    log,
    queue,
    supersede: () => {
      current = false;
    },
  };
}

const list: Item[] = ["a", "b", "c", "d", "e"].map((id) => ({ id }));

describe("loadQueueInStages", () => {
  it("plays after exactly one sign call, before the others are signed", async () => {
    const { deps, log } = harness(list, 2);
    await loadQueueInStages(deps);
    const playAt = log.indexOf("play");
    const before = log.slice(0, playAt);
    expect(before.filter((l) => l.startsWith("sign:"))).toEqual(["sign:c"]);
    expect(before).toEqual(["sign:c", "reset", "add:c@end", "skip:0"]);
    const after = log.slice(playAt + 1);
    expect(after.filter((l) => l.startsWith("sign:")).sort()).toEqual(["sign:a", "sign:b", "sign:d", "sign:e"]);
  });

  it("puts the tracks behind and ahead in list order around the tapped one", async () => {
    const { deps, queue } = harness(list, 2);
    expect(await loadQueueInStages(deps)).toBe("loaded");
    expect(queue).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("adds the tracks behind in front of the playing track, not at the end", async () => {
    const { deps, log } = harness(list, 3);
    await loadQueueInStages(deps);
    expect(log).toContain("add:a,b,c@0");
    expect(log).toContain("add:e@end");
  });

  it("starts the first item when the tapped one is first", async () => {
    const { deps, queue, log } = harness(list, 0);
    await loadQueueInStages(deps);
    expect(queue).toEqual(["a", "b", "c", "d", "e"]);
    expect(log.some((l) => l.endsWith("@0"))).toBe(false);
  });

  it("starts at the next playable track when the tapped one cannot play", async () => {
    const items: Item[] = [{ id: "a" }, { id: "b", playable: false }, { id: "c" }, { id: "d" }];
    const { deps, queue, log } = harness(items, 1);
    expect(await loadQueueInStages(deps)).toBe("loaded");
    expect(queue).toEqual(["a", "c", "d"]);
    expect(log.indexOf("play")).toBeGreaterThan(log.indexOf("add:c@end"));
  });

  it("leaves unplayable tracks out of the queue", async () => {
    const items: Item[] = [{ id: "a", playable: false }, { id: "b" }, { id: "c", playable: false }, { id: "d" }];
    const { deps, queue } = harness(items, 1);
    await loadQueueInStages(deps);
    expect(queue).toEqual(["b", "d"]);
  });

  it("does nothing to the player when nothing can play", async () => {
    const items: Item[] = [{ id: "a", playable: false }, { id: "b", playable: false }];
    const { deps, log } = harness(items, 0);
    expect(await loadQueueInStages(deps)).toBe("empty");
    expect(log.some((l) => l === "reset" || l === "play" || l.startsWith("add:"))).toBe(false);
  });

  it("stops before reset when superseded while signing the tapped track", async () => {
    const h = harness(list, 2);
    h.deps.sign = async (item) => {
      h.log.push(`sign:${item.id}`);
      h.supersede();
      return item.id;
    };
    expect(await loadQueueInStages(h.deps)).toBe("superseded");
    expect(h.log).toEqual(["sign:c"]);
  });

  it("stops before any further add when superseded after play", async () => {
    const h = harness(list, 2);
    h.deps.play = async () => {
      h.log.push("play");
      h.supersede();
    };
    expect(await loadQueueInStages(h.deps)).toBe("superseded");
    expect(h.log.filter((l) => l.startsWith("add:"))).toEqual(["add:c@end"]);
  });

  it("stops between the ahead and behind adds when superseded in between", async () => {
    const h = harness(list, 2);
    const realAdd = h.deps.add;
    h.deps.add = async (entries, at) => {
      await realAdd(entries, at);
      if (entries.join(",") === "d,e") h.supersede();
    };
    expect(await loadQueueInStages(h.deps)).toBe("superseded");
    expect(h.log.filter((l) => l.startsWith("add:"))).toEqual(["add:c@end", "add:d,e@end"]);
  });

  it("calls onStarted once, right after play", async () => {
    const h = harness(list, 1);
    const onStarted = jest.fn(() => {
      h.log.push("started");
    });
    h.deps.onStarted = onStarted;
    await loadQueueInStages(h.deps);
    expect(onStarted).toHaveBeenCalledTimes(1);
    expect(h.log[h.log.indexOf("play") + 1]).toBe("started");
  });
});
