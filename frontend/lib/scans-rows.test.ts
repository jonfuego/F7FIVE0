// node:test coverage for the Admin > Scans rows: which source drives each row,
// which buttons are on and why not, what Scan all starts, and the folded line.
//
// Run: node --test frontend/lib/scans-rows.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildScanRows, scanAllPlan, scanErrors, scansSummary,
  type ArrApps, type ArrSyncLike, type FolderScanLike, type MusicVideosLike, type PodcastRefreshLike,
  type ScanInputs, type ScanRow,
} from "./scans-rows.ts";

const NONE: ArrApps = { radarr: false, sonarr: false, lidarr: false };
const FOLDERS = { movies: 1, tv: 1, music: 1, music_videos: 1, podcasts: 1 };

const idleFolder: FolderScanLike = {
  state: "idle", finished_at: null, scope: null, libraries: {}, last_error: null,
};
const idleMv: MusicVideosLike = {
  state: "idle", finished_at: null, total: 0, count: 0, added: 0, missing: 0, errors: 0, last_error: null,
};
const idleArr: ArrSyncLike = { state: "idle", finished_at: null, current_app: null, apps: {}, last_error: null };
const idlePodcasts: PodcastRefreshLike = {
  state: "idle", finished_at: null, total: 0, count: 0, added: 0, errors: 0, last_error: null,
};

function inputs(over: Partial<ScanInputs> = {}): ScanInputs {
  return {
    apps: NONE, folders: FOLDERS, folder: idleFolder, musicVideos: idleMv, arr: idleArr,
    podcastRefresh: idlePodcasts, now: Date.parse("2026-10-11T12:00:00Z"), ...over,
  };
}

function row(rows: ScanRow[], id: string): ScanRow {
  const r = rows.find((x) => x.id === id);
  assert.ok(r, `row ${id} is missing`);
  return r;
}

// -- order and which rows exist ----------------------------------------------
test("row order is Movies, TV, Music, Music videos, Podcasts, Podcast feeds, *arr sync", () => {
  const rows = buildScanRows(inputs({ apps: { radarr: true, sonarr: true, lidarr: true } }));
  assert.deepEqual(rows.map((r) => r.id), [
    "movies", "tv", "music", "music_videos", "podcasts", "podcast_feeds", "arr",
  ]);
  assert.deepEqual(rows.map((r) => r.label), [
    "Movies", "TV", "Music", "Music videos", "Podcasts", "Podcast feeds", "*arr sync",
  ]);
});

test("the *arr sync row appears only when an app is set", () => {
  assert.deepEqual(buildScanRows(inputs()).map((r) => r.id), [
    "movies", "tv", "music", "music_videos", "podcasts", "podcast_feeds",
  ]);
  for (const app of ["radarr", "sonarr", "lidarr"] as const) {
    const rows = buildScanRows(inputs({ apps: { ...NONE, [app]: true } }));
    assert.equal(rows.at(-1)?.id, "arr", `${app} alone shows the *arr sync row`);
  }
});

test("the Music videos row always appears, even with no folder or no status yet", () => {
  assert.ok(buildScanRows(inputs()).some((r) => r.id === "music_videos"));
  const bare = buildScanRows({ apps: null, folders: null, folder: null, musicVideos: null, arr: null });
  assert.ok(bare.some((r) => r.id === "music_videos"));
});

// -- the source behind each library -------------------------------------------
test("Music is driven by the folder scan when Lidarr is not set", () => {
  const music = row(buildScanRows(inputs()), "music");
  assert.equal(music.source, "folder scan");
  assert.deepEqual(music.action, { kind: "folder", library: "music" });
  assert.equal(music.canStart, true);
  assert.equal(music.disabledReason, null);
});

test("Music is driven by the Lidarr sync when Lidarr is set, never the folder scan", () => {
  const music = row(buildScanRows(inputs({ apps: { ...NONE, lidarr: true } })), "music");
  assert.equal(music.source, "Lidarr sync");
  assert.deepEqual(music.action, { kind: "arr", apps: ["lidarr"] });
  assert.equal(music.canStart, true);
});

test("Music stays startable with or without Lidarr (the 2026-10-11 gap)", () => {
  for (const lidarr of [false, true]) {
    const music = row(buildScanRows(inputs({ apps: { ...NONE, lidarr } })), "music");
    assert.equal(music.canStart, true, `lidarr=${lidarr}`);
  }
});

test("Movies and TV follow Radarr and Sonarr being set", () => {
  const folderRows = buildScanRows(inputs());
  assert.equal(row(folderRows, "movies").source, "folder scan");
  assert.equal(row(folderRows, "tv").source, "folder scan");

  const arrRows = buildScanRows(inputs({ apps: { radarr: true, sonarr: true, lidarr: false } }));
  assert.equal(row(arrRows, "movies").source, "Radarr sync");
  assert.deepEqual(row(arrRows, "movies").action, { kind: "arr", apps: ["radarr"] });
  assert.equal(row(arrRows, "tv").source, "Sonarr sync");
  assert.equal(row(arrRows, "music").source, "folder scan", "no Lidarr: music still uses the folder scan");

  const mixed = buildScanRows(inputs({ apps: { radarr: true, sonarr: false, lidarr: false } }));
  assert.equal(row(mixed, "movies").source, "Radarr sync");
  assert.equal(row(mixed, "tv").source, "folder scan");
});

test("a library with an *arr app does not need a folder to be startable", () => {
  const rows = buildScanRows(inputs({
    apps: { ...NONE, lidarr: true }, folders: { movies: 1, tv: 1, music: 0, music_videos: 1 },
  }));
  assert.equal(row(rows, "music").canStart, true);
});

test("the music videos row uses the music videos scan", () => {
  const mv = row(buildScanRows(inputs()), "music_videos");
  assert.equal(mv.source, "music videos scan");
  assert.deepEqual(mv.action, { kind: "music_videos" });
});

// -- buttons and the reason they are off ---------------------------------------
test("a folder row with no folder is off and says to add one", () => {
  const rows = buildScanRows(inputs({ folders: { movies: 1, tv: 1, music: 0, music_videos: 0 } }));
  const music = row(rows, "music");
  assert.equal(music.canStart, false);
  assert.equal(music.disabledReason, "Add a Music folder under Library folders first.");
  assert.equal(row(rows, "music_videos").disabledReason, "Add a Music videos folder under Library folders first.");
  assert.equal(row(rows, "movies").canStart, true);
});

test("while the folder scan runs, every folder row is off and the running one says so", () => {
  const folder: FolderScanLike = {
    state: "running", finished_at: null, scope: null,
    libraries: {
      movies: { state: "done", total: 10, seen: 10, added: 10 },
      tv: { state: "running", total: 100, seen: 40 },
    },
    last_error: null,
  };
  const rows = buildScanRows(inputs({ folder }));
  assert.equal(row(rows, "movies").state, "idle");
  assert.equal(row(rows, "movies").disabledReason, "A folder scan is already running.");
  const tv = row(rows, "tv");
  assert.equal(tv.state, "running");
  assert.equal(tv.disabledReason, "Scanning now.");
  assert.deepEqual(tv.progress, { done: 40, total: 100, percent: 40 });
  assert.equal(tv.result, "40 of 100 files");
  // Music is waiting its turn inside the same scan.
  const music = row(rows, "music");
  assert.equal(music.state, "running");
  assert.equal(music.result, "Waiting its turn");
  // The music videos scan is a different job and stays startable.
  assert.equal(row(rows, "music_videos").canStart, true);
});

test("a scan of one library leaves the other rows as they were", () => {
  const folder: FolderScanLike = {
    state: "running", finished_at: "2026-10-11T11:00:00Z", scope: ["music"],
    libraries: { movies: { state: "done", total: 5, seen: 5, added: 5 } },
    last_error: null,
  };
  const rows = buildScanRows(inputs({ folder }));
  assert.equal(row(rows, "music").state, "running");
  assert.equal(row(rows, "movies").state, "idle", "not in scope, keeps its last result");
  assert.equal(row(rows, "tv").state, "never", "not in scope and never scanned");
});

test("everything is off, with a reason, until the statuses are known", () => {
  const rows = buildScanRows({ apps: null, folders: null, folder: null, musicVideos: null, arr: null });
  assert.ok(rows.every((r) => !r.canStart && r.disabledReason === "Still checking."));
});

test("an *arr app row is off while an *arr sync runs, and the app running says Syncing now", () => {
  const arr: ArrSyncLike = {
    state: "running", finished_at: null, current_app: "radarr",
    apps: { radarr: { state: "running", synced: 0, errors: 0 }, lidarr: { state: "queued", synced: 0, errors: 0 } },
    last_error: null,
  };
  const rows = buildScanRows(inputs({ apps: { radarr: true, sonarr: true, lidarr: true }, arr }));
  assert.equal(row(rows, "movies").state, "running");
  assert.equal(row(rows, "movies").disabledReason, "Syncing now.");
  assert.equal(row(rows, "music").result, "Waiting its turn");
  assert.equal(row(rows, "tv").state, "never");
  assert.equal(row(rows, "tv").disabledReason, "An *arr sync is already running.");
  const all = row(rows, "arr");
  assert.equal(all.state, "running");
  assert.equal(all.result, "Syncing Radarr");
  assert.equal(all.canStart, false);
});

// -- state and result text -------------------------------------------------------
test("states: never, idle, running, error", () => {
  assert.equal(row(buildScanRows(inputs()), "movies").state, "never");
  assert.equal(row(buildScanRows(inputs()), "movies").result, "Not scanned yet");

  const done: FolderScanLike = {
    state: "idle", finished_at: "2026-10-11T11:55:00Z", scope: null,
    libraries: {
      movies: { state: "done", total: 12, seen: 12, added: 12, missing: 1 },
      tv: { state: "failed", seen: 3 },
      music: { state: "done", seen: 20, added: 18, errors: 2 },
    },
    last_error: "music scan failed: share went away",
  };
  const rows = buildScanRows(inputs({ folder: done }));
  const movies = row(rows, "movies");
  assert.equal(movies.state, "idle");
  assert.equal(movies.result, "12 files seen, 12 added, 1 missing");
  assert.equal(movies.when, "Finished 5 minutes ago");
  assert.equal(row(rows, "tv").state, "error");
  assert.equal(row(rows, "tv").result, "Failed");
  assert.equal(row(rows, "music").state, "error", "a finished library with errors needs a look");
  assert.equal(row(rows, "music").result, "20 files seen, 18 added, 2 errors");
});

test("music videos: running shows x of y, done shows counts, errors turn it red", () => {
  const running = buildScanRows(inputs({
    musicVideos: { ...idleMv, state: "running", total: 30, count: 15 },
  }));
  const mv = row(running, "music_videos");
  assert.equal(mv.state, "running");
  assert.equal(mv.result, "15 of 30 files");
  assert.deepEqual(mv.progress, { done: 15, total: 30, percent: 50 });
  assert.equal(mv.disabledReason, "Scanning now.");

  const finished = row(buildScanRows(inputs({
    musicVideos: { ...idleMv, finished_at: "2026-10-11T11:00:00Z", total: 30, count: 30, added: 28, errors: 1 },
  })), "music_videos");
  assert.equal(finished.state, "error");
  assert.equal(finished.result, "28 added, 1 error");
  assert.equal(finished.when, "Finished 1 hour ago");
});

test("the *arr sync row sums up each app that is set", () => {
  const arr: ArrSyncLike = {
    state: "idle", finished_at: "2026-10-11T11:59:00Z", current_app: null,
    apps: {
      radarr: { state: "done", synced: 12, errors: 0 },
      lidarr: { state: "done", synced: 30, errors: 0 },
    },
    last_error: null,
  };
  const rows = buildScanRows(inputs({ apps: { radarr: true, sonarr: false, lidarr: true }, arr }));
  const all = row(rows, "arr");
  assert.equal(all.state, "idle");
  assert.equal(all.result, "Radarr 12 movies, Lidarr 30 artists");
  assert.deepEqual(all.action, { kind: "arr", apps: ["radarr", "lidarr"] });
  assert.equal(all.canStart, true);
  assert.equal(row(rows, "movies").result, "12 movies synced");
});

// -- Scan all -------------------------------------------------------------------
test("Scan all covers exactly the rows that can start", () => {
  const rows = buildScanRows(inputs({
    folders: { movies: 1, tv: 0, music: 1, music_videos: 0 },
  }));
  const plan = scanAllPlan(rows);
  assert.deepEqual(plan.rowIds, ["movies", "music"], "TV and Music videos have no folder");
  assert.deepEqual(plan.libraries, ["movies", "music"]);
  assert.deepEqual(plan.arrApps, []);
  assert.equal(plan.musicVideos, false);
  assert.deepEqual(
    plan.rowIds,
    rows.filter((r) => r.canStart && r.id !== "podcast_feeds").map((r) => r.id),
    "every startable row except Refresh feeds, which has its own button",
  );
});

test("Scan all skips rows that are already running", () => {
  const folder: FolderScanLike = {
    state: "running", finished_at: null, scope: null,
    libraries: { movies: { state: "running", total: 10, seen: 2 } }, last_error: null,
  };
  const musicVideos: MusicVideosLike = { ...idleMv, state: "running", total: 5, count: 1 };
  const rows = buildScanRows(inputs({ folder, musicVideos }));
  assert.deepEqual(scanAllPlan(rows), { rowIds: [], libraries: [], arrApps: [], musicVideos: false });
});

test("Scan all with Lidarr set starts the Lidarr sync for Music, not the folder scan", () => {
  const rows = buildScanRows(inputs({ apps: { ...NONE, lidarr: true } }));
  const plan = scanAllPlan(rows);
  assert.deepEqual(plan.rowIds, ["movies", "tv", "music", "music_videos", "podcasts", "arr"]);
  assert.deepEqual(plan.libraries, ["movies", "tv", "podcasts"], "music is not in the folder scan");
  assert.deepEqual(plan.arrApps, ["lidarr"], "one sync request, no duplicate app");
  assert.equal(plan.musicVideos, true);
});

test("Scan all with every app set starts one sync and the music videos scan only", () => {
  const rows = buildScanRows(inputs({ apps: { radarr: true, sonarr: true, lidarr: true } }));
  const plan = scanAllPlan(rows);
  assert.deepEqual(plan.libraries, ["podcasts"], "only the podcasts folder scan is left");
  assert.deepEqual(plan.arrApps, ["radarr", "sonarr", "lidarr"]);
  assert.equal(plan.musicVideos, true);
});

test("Scan all skips a running *arr sync but still starts the folder rows", () => {
  const arr: ArrSyncLike = {
    state: "running", finished_at: null, current_app: "lidarr",
    apps: { lidarr: { state: "running", synced: 0, errors: 0 } }, last_error: null,
  };
  const plan = scanAllPlan(buildScanRows(inputs({ apps: { ...NONE, lidarr: true }, arr })));
  assert.deepEqual(plan.rowIds, ["movies", "tv", "music_videos", "podcasts"]);
  assert.deepEqual(plan.arrApps, []);
});

// -- folded line and errors --------------------------------------------------------
test("summary: running needs attention, errors need attention, idle does not", () => {
  assert.deepEqual(scansSummary(buildScanRows(inputs())), { text: "Not scanned yet", attention: false });

  const running: FolderScanLike = {
    state: "running", finished_at: null, scope: ["music"],
    libraries: { music: { state: "running", total: 200, seen: 80 } }, last_error: null,
  };
  assert.deepEqual(scansSummary(buildScanRows(inputs({ folder: running }))), {
    text: "Running: Music 40%", attention: true,
  });

  const failed: FolderScanLike = {
    state: "idle", finished_at: "2026-10-11T11:00:00Z", scope: null,
    libraries: { tv: { state: "failed" }, movies: { state: "done", seen: 1, added: 1 } }, last_error: null,
  };
  assert.deepEqual(scansSummary(buildScanRows(inputs({ folder: failed }))), {
    text: "Needs attention: TV", attention: true,
  });

  const ok: FolderScanLike = {
    state: "idle", finished_at: "2026-10-11T11:00:00Z", scope: null,
    libraries: { movies: { state: "done", seen: 1, added: 1 } }, last_error: null,
  };
  assert.deepEqual(scansSummary(buildScanRows(inputs({ folder: ok }))), { text: "Up to date", attention: false });
});

test("errors: each status's last error once, blanks dropped", () => {
  const folder: FolderScanLike = { ...idleFolder, last_error: "The scan stopped: x" };
  const mv: MusicVideosLike = { ...idleMv, last_error: "The scan stopped: x" };
  const arr: ArrSyncLike = { ...idleArr, last_error: " radarr sync failed: down " };
  assert.deepEqual(scanErrors(inputs({ folder, musicVideos: mv, arr })), [
    "The scan stopped: x", "radarr sync failed: down",
  ]);
  assert.deepEqual(scanErrors(inputs()), []);
});

// -- podcasts ----------------------------------------------------------------------
test("the Podcasts row is a folder scan of the podcasts library, never an *arr sync", () => {
  const podcasts = row(buildScanRows(inputs({ apps: { radarr: true, sonarr: true, lidarr: true } })), "podcasts");
  assert.equal(podcasts.source, "folder scan");
  assert.deepEqual(podcasts.action, { kind: "folder", library: "podcasts" });
  assert.equal(podcasts.canStart, true);
});

test("the Podcasts row is off, with a reason, when there is no podcasts folder", () => {
  const rows = buildScanRows(inputs({ folders: { movies: 1, tv: 1, music: 1, music_videos: 1, podcasts: 0 } }));
  const podcasts = row(rows, "podcasts");
  assert.equal(podcasts.canStart, false);
  assert.equal(podcasts.disabledReason, "Add a Podcasts folder under Library folders first.");
});

test("the Podcasts row follows the folder scan: running, counts, errors", () => {
  const running: FolderScanLike = {
    state: "running", finished_at: null, scope: ["podcasts"],
    libraries: { podcasts: { state: "running", total: 40, seen: 10 } }, last_error: null,
  };
  const r = row(buildScanRows(inputs({ folder: running })), "podcasts");
  assert.equal(r.state, "running");
  assert.equal(r.result, "10 of 40 files");
  assert.deepEqual(r.progress, { done: 10, total: 40, percent: 25 });

  const done: FolderScanLike = {
    state: "idle", finished_at: "2026-10-11T11:55:00Z", scope: null,
    libraries: { podcasts: { state: "done", seen: 12, added: 12 } }, last_error: null,
  };
  assert.equal(row(buildScanRows(inputs({ folder: done })), "podcasts").result, "12 files seen, 12 added");
});

test("the Podcast feeds row refreshes feeds with its own button and says what it found", () => {
  const never = row(buildScanRows(inputs()), "podcast_feeds");
  assert.equal(never.source, "feed refresh");
  assert.deepEqual(never.action, { kind: "podcast_refresh" });
  assert.equal(never.state, "never");
  assert.equal(never.result, "Not refreshed yet");
  assert.equal(never.canStart, true);

  const running = row(buildScanRows(inputs({
    podcastRefresh: { ...idlePodcasts, state: "running", total: 8, count: 2 },
  })), "podcast_feeds");
  assert.equal(running.state, "running");
  assert.equal(running.result, "2 of 8 shows");
  assert.deepEqual(running.progress, { done: 2, total: 8, percent: 25 });
  assert.equal(running.canStart, false);
  assert.equal(running.disabledReason, "Refreshing now.");

  const done = row(buildScanRows(inputs({
    podcastRefresh: { ...idlePodcasts, finished_at: "2026-10-11T11:00:00Z", total: 8, count: 8, added: 5, errors: 1 },
  })), "podcast_feeds");
  assert.equal(done.state, "error");
  assert.equal(done.result, "5 new episodes, 1 error");
  assert.equal(done.when, "Finished 1 hour ago");
  const one = row(buildScanRows(inputs({
    podcastRefresh: { ...idlePodcasts, finished_at: "2026-10-11T11:00:00Z", added: 1 },
  })), "podcast_feeds");
  assert.equal(one.state, "idle");
  assert.equal(one.result, "1 new episode");
});

test("Scan all does not refresh podcast feeds; that has its own button", () => {
  const plan = scanAllPlan(buildScanRows(inputs()));
  assert.ok(!plan.rowIds.includes("podcast_feeds" as never));
  assert.ok(plan.rowIds.includes("podcasts"));
  assert.ok(plan.libraries.includes("podcasts"));
});

test("a podcast refresh error shows under the list", () => {
  assert.deepEqual(scanErrors(inputs({
    podcastRefresh: { ...idlePodcasts, last_error: "The last scan was interrupted" },
  })), ["The last scan was interrupted"]);
});

