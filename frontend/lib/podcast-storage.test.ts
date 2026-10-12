// node:test coverage for the Admin podcast storage line and its warning.
//
// Run: node --test frontend/lib/podcast-storage.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { storageSummary, storageWarning, type PodcastStorage } from "./podcast-storage.ts";

const GB = 1024 ** 3;

function storage(over: Partial<PodcastStorage> = {}): PodcastStorage {
  return {
    used_bytes: 3 * GB,
    warn_gb: 10,
    low_space: false,
    folders: [{ path: "D:\\Podcasts", reachable: true, free_bytes: 50 * GB, total_bytes: 100 * GB }],
    ...over,
  };
}

test("no warning while there is room", () => {
  assert.equal(storageWarning(storage()), null);
});

test("the warning names the folder, what is free and the threshold", () => {
  const low = storage({
    low_space: true,
    folders: [{ path: "D:\\Podcasts", reachable: true, free_bytes: 7 * GB, total_bytes: 100 * GB }],
  });
  assert.equal(
    storageWarning(low),
    "Podcast storage is low: D:\\Podcasts has 7.0 GB free (the warning starts below 10 GB).",
  );
});

test("the warning picks the folder with the least room and skips unreachable ones", () => {
  const low = storage({
    low_space: true,
    folders: [
      { path: "E:\\Gone", reachable: false, free_bytes: null, total_bytes: null },
      { path: "D:\\A", reachable: true, free_bytes: 9 * GB, total_bytes: 100 * GB },
      { path: "\\\\nas\\pod", reachable: true, free_bytes: 2 * GB, total_bytes: 100 * GB },
    ],
  });
  assert.match(storageWarning(low) ?? "", /\\\\nas\\pod has 2\.0 GB free/);
});

test("the summary says what the downloads use and how much is free", () => {
  assert.equal(storageSummary(storage()), "3.0 GB downloaded. D:\\Podcasts: 50.0 GB free of 100.0 GB.");
  assert.equal(storageSummary(storage({ folders: [], used_bytes: 0 })), "No podcasts folder yet.");
});
