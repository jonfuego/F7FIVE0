// node:test coverage for the Admin dashboard rules: what needs attention, the
// meter threshold, the tile summaries and the old /admin#<section> links.
//
// Run: node --test frontend/lib/admin-dashboard.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ADMIN_AREAS,
  ADMIN_HASH_MAP,
  SLOW_TRANSCODE_SEC,
  adminRedirectForHash,
  buildAttentionItems,
  currentAreaId,
  eventLines,
  libraryTile,
  meterState,
  relativeTime,
  remoteTile,
  resolveAdminHref,
  settingsTiles,
  storageMeters,
  streamLines,
  streamingTile,
  versionTile,
  type AttentionInputs,
  type SessionLike,
  type TranscodeLike,
  type UpdatesLike,
} from "./admin-dashboard.ts";
import { buildScanRows, type ScanInputs } from "./scans-rows.ts";

const NOW = Date.parse("2026-10-17T12:00:00Z");

function transcode(over: Partial<TranscodeLike> = {}): TranscodeLike {
  return {
    id: "t1",
    user_id: "u1",
    user_display_name: "Jon",
    title: "Dune",
    variant: "720p",
    direct_play: false,
    started_at: "2026-10-17T11:55:00Z",
    bytes_served: 5 * 1024 * 1024,
    speed: 0.82,
    below_realtime_sec: 0,
    ...over,
  };
}

const quiet: AttentionInputs = {
  reminders: [],
  transcodes: [],
  scanRows: [],
  updates: {
    installed_version: "1.0.14",
    phone_app_version: "1.0.14",
    latest_version: "1.0.14",
    update_available: false,
    checked_at: "2026-10-17T11:00:00Z",
    run: null,
  },
  remote: { public_url: "https://f7.example.com", method: "cloudflare", reachable: true },
};

function scanRowsWith(folder: ScanInputs["folder"]) {
  return buildScanRows({
    apps: { radarr: false, sonarr: false, lidarr: false },
    folders: { movies: 1, tv: 1, music: 1, music_videos: 0, podcasts: 0 },
    folder,
    musicVideos: null,
    arr: null,
    now: NOW,
  });
}

test("needs attention: a stream 29 s below realtime is fine, 30 s is flagged", () => {
  assert.equal(SLOW_TRANSCODE_SEC, 30);
  const at29 = buildAttentionItems({ ...quiet, transcodes: [transcode({ below_realtime_sec: 29 })] });
  assert.deepEqual(at29, []);

  const at30 = buildAttentionItems({ ...quiet, transcodes: [transcode({ below_realtime_sec: 30 })] });
  assert.equal(at30.length, 1);
  assert.equal(at30[0].kind, "transcode");
  assert.equal(
    at30[0].text,
    "Jon's stream of Dune is transcoding below realtime (0.82x for 30 s)",
  );
  assert.equal(at30[0].href, "/admin#streaming-now");
});

test("needs attention: direct play never counts as slow", () => {
  const items = buildAttentionItems({
    ...quiet,
    transcodes: [transcode({ direct_play: true, speed: null, below_realtime_sec: 120 })],
  });
  assert.deepEqual(items, []);
});

test("needs attention: reminders become items with their own link", () => {
  const items = buildAttentionItems({
    ...quiet,
    reminders: [
      {
        id: "tmdb_key",
        title: "Add a TMDB key",
        body: "Posters and details need one.",
        action_label: "Add key",
        action_href: "/admin#metadata",
      },
    ],
  });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "reminder");
  assert.equal(items[0].text, "Add a TMDB key");
  assert.equal(items[0].detail, "Posters and details need one.");
  assert.equal(items[0].linkLabel, "Add key");
  // The backend still says /admin#metadata; the item links straight to the subpage.
  assert.equal(items[0].href, "/admin/metadata");
});

test("resolveAdminHref: old anchors become subpages, everything else is left alone", () => {
  assert.equal(resolveAdminHref("/admin#metadata"), "/admin/metadata");
  assert.equal(resolveAdminHref("/admin#library-folders"), "/admin/library-folders");
  assert.equal(resolveAdminHref("/admin#health"), "/admin#health");
  assert.equal(resolveAdminHref("/admin/updates"), "/admin/updates");
  assert.equal(resolveAdminHref("/account"), "/account");
});

test("needs attention: a failed scan", () => {
  const rows = scanRowsWith({
    state: "idle",
    finished_at: "2026-10-17T11:00:00Z",
    scope: null,
    libraries: { movies: { state: "failed" }, tv: { state: "done", seen: 3, added: 3 } },
    last_error: null,
  });
  const items = buildAttentionItems({ ...quiet, scanRows: rows });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "scan");
  assert.equal(items[0].text, "Movies scan needs attention: Failed");
  assert.equal(items[0].href, "/admin/scans");
});

test("needs attention: an update ready to install", () => {
  const updates: UpdatesLike = {
    ...(quiet.updates as UpdatesLike),
    latest_version: "1.0.15",
    update_available: true,
  };
  const items = buildAttentionItems({ ...quiet, updates });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "update");
  assert.equal(items[0].text, "F7FIVE0 1.0.15 is ready to install");
  assert.equal(items[0].href, "/admin/updates");

  // An update that is already running is not "ready to install".
  const running = buildAttentionItems({ ...quiet, updates: { ...updates, run: { active: true } } });
  assert.deepEqual(running, []);
});

test("needs attention: remote access set up but not reachable", () => {
  const items = buildAttentionItems({
    ...quiet,
    remote: { public_url: "https://f7.example.com", method: "cloudflare", reachable: false },
  });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "remote");
  assert.match(items[0].text, /not reachable/);
  assert.equal(items[0].href, "/admin/remote-access");

  // Off is not a problem.
  const off = buildAttentionItems({ ...quiet, remote: { public_url: null, method: null, reachable: null } });
  assert.deepEqual(off, []);
});

test("needs attention: an *arr root folder the service cannot open (B2.5)", () => {
  const roots = [
    { app: "radarr", label: "Radarr", path: "N:\\Movies", translated: "N:\\Movies", mapped: false, reachable: false, drive: "N:" },
    { app: "sonarr", label: "Sonarr", path: "\\\\nas\\TV", translated: "\\\\nas\\TV", mapped: false, reachable: true, drive: null },
    { app: "lidarr", label: "Lidarr", path: "D:\\Music", translated: "D:\\Music", mapped: false, reachable: false, drive: null },
  ];
  const items = buildAttentionItems({ ...quiet, arrRoots: roots });
  assert.equal(items.length, 2, "the reachable one adds nothing");
  assert.equal(items[0].kind, "root");
  assert.equal(items[0].text, "Radarr's folder N:\\Movies is on drive N:, which the F7FIVE0 service can't see");
  assert.equal(items[0].linkLabel, "Add a path mapping");
  assert.equal(items[0].href, "/admin/library-folders");
  assert.equal(items[1].text, "Lidarr's folder D:\\Music can't be opened by the F7FIVE0 service");
  assert.deepEqual(buildAttentionItems({ ...quiet, arrRoots: null }), []);
  assert.deepEqual(buildAttentionItems({ ...quiet, arrRoots: roots.filter((r) => r.reachable) }), []);
});

test("needs attention: nothing wrong, or nothing loaded, gives no items", () => {
  assert.deepEqual(buildAttentionItems(quiet), []);
  assert.deepEqual(
    buildAttentionItems({ reminders: null, transcodes: null, scanRows: null, updates: null, remote: null }),
    [],
  );
});

test("needs attention: items come in a fixed order", () => {
  const rows = scanRowsWith({
    state: "idle",
    finished_at: "2026-10-17T11:00:00Z",
    scope: null,
    libraries: { movies: { state: "failed" } },
    last_error: null,
  });
  const items = buildAttentionItems({
    reminders: [{ id: "r", title: "R", body: "", action_label: "Go", action_href: "/admin" }],
    transcodes: [transcode({ below_realtime_sec: 60 })],
    scanRows: rows,
    updates: { ...(quiet.updates as UpdatesLike), latest_version: "1.0.15", update_available: true },
    remote: { public_url: "https://x", method: "tailscale", reachable: false },
    arrRoots: [{ app: "radarr", label: "Radarr", path: "N:\\M", translated: "N:\\M", mapped: false, reachable: false, drive: "N:" }],
  });
  assert.deepEqual(items.map((i) => i.kind), ["reminder", "transcode", "scan", "root", "update", "remote"]);
});

test("meter: 89 percent is normal, 90 percent warns", () => {
  assert.deepEqual(meterState(89, 100), { percent: 89, warn: false, word: null });
  assert.deepEqual(meterState(90, 100), { percent: 90, warn: true, word: "Almost full" });
  // 89.9 percent floors to 89, so it does not warn early.
  assert.equal(meterState(899, 1000).warn, false);
  assert.equal(meterState(100, 100).percent, 100);
  // Over the cap clamps, no total reads empty.
  assert.equal(meterState(150, 100).percent, 100);
  assert.deepEqual(meterState(5, 0), { percent: 0, warn: false, word: null });
});

test("storage meters: cache toward its cap, drives by how much is used", () => {
  const gb = 1024 ** 3;
  const meters = storageMeters({
    transcode_cache_bytes: 9 * gb,
    transcode_cache_max_bytes: 10 * gb,
    cache_disk_free_bytes: 50 * gb,
    cache_disk_total_bytes: 100 * gb,
    art_disk_free_bytes: 5 * gb,
    art_disk_total_bytes: 100 * gb,
    open_transcode_sessions: 0,
    last_sync_at: null,
  });
  assert.deepEqual(meters.map((m) => m.id), ["cache", "cache-disk", "art-disk"]);
  assert.equal(meters[0].warn, true);
  assert.equal(meters[0].value, "9.0 GB of 10 GB");
  assert.equal(meters[1].percent, 50);
  assert.equal(meters[1].warn, false);
  assert.equal(meters[2].percent, 95);
  assert.equal(meters[2].word, "Almost full");
});

test("old hashes: every row of the redirect table", () => {
  const expected: Record<string, string | null> = {
    "#users": "/admin/users",
    "#updates": "/admin/updates",
    "#remote-access": "/admin/remote-access",
    "#library-folders": "/admin/library-folders",
    "#scans": "/admin/scans",
    "#metadata": "/admin/metadata",
    "#arr": "/admin/arr",
    "#audio-analysis": "/admin/audio-analysis",
    "#library-health": "/admin/library-health",
    "#sessions": "/admin/activity",
    "#auth-events": "/admin/activity",
    "#history": "/admin/activity",
    "#health": null,
    "#active-streams": null,
  };
  for (const [hash, to] of Object.entries(expected)) {
    assert.equal(adminRedirectForHash(hash), to, hash);
    // The hash also works without the "#".
    assert.equal(adminRedirectForHash(hash.slice(1)), to, hash.slice(1));
  }
  assert.equal(Object.keys(ADMIN_HASH_MAP).length, Object.keys(expected).length);
});

test("old hashes: no hash, an unknown hash and the new anchor stay put", () => {
  assert.equal(adminRedirectForHash(""), null);
  assert.equal(adminRedirectForHash("#"), null);
  assert.equal(adminRedirectForHash(null), null);
  assert.equal(adminRedirectForHash("#nonsense"), null);
  assert.equal(adminRedirectForHash("#streaming-now"), null);
  // Inherited object keys are not sections.
  assert.equal(adminRedirectForHash("#constructor"), null);
});

test("section list: ten areas, each reachable from its own path", () => {
  assert.equal(ADMIN_AREAS.length, 10);
  for (const area of ADMIN_AREAS) {
    assert.equal(currentAreaId(area.href), area.id);
    assert.equal(currentAreaId(`${area.href}/`), area.id);
  }
  assert.equal(currentAreaId("/admin"), null);
  assert.equal(currentAreaId("/admin/"), null);
  assert.equal(currentAreaId("/admin/users-extra"), null);
  assert.equal(currentAreaId(null), null);
  // Every hash target is a real area or the overview.
  const hrefs = new Set(ADMIN_AREAS.map((a) => a.href));
  for (const target of Object.values(ADMIN_HASH_MAP)) {
    assert.ok(target === "/admin" || hrefs.has(target), target);
  }
});

test("version tile: up to date, update available, updating", () => {
  const base: UpdatesLike = {
    installed_version: "1.0.14",
    phone_app_version: "1.0.14",
    latest_version: "1.0.14",
    update_available: false,
    checked_at: "2026-10-17T11:55:00Z",
    run: null,
  };
  const current = versionTile(base, NOW);
  assert.equal(current.state, "current");
  assert.equal(current.buttonLabel, null);
  assert.equal(current.checked, "Checked 5 minutes ago");

  const avail = versionTile({ ...base, latest_version: "1.0.15", update_available: true }, NOW);
  assert.equal(avail.state, "available");
  assert.equal(avail.buttonLabel, "Update to 1.0.15");

  const busy = versionTile({ ...base, latest_version: "1.0.15", update_available: true, run: { active: true } }, NOW);
  assert.equal(busy.state, "updating");
  assert.equal(busy.buttonLabel, null);

  const fresh = versionTile({ ...base, latest_version: null, checked_at: null }, NOW);
  assert.equal(fresh.state, "unknown");
  assert.equal(fresh.checked, "Not checked yet");
});

test("remote tile: connected, not reachable, off", () => {
  assert.deepEqual(
    remoteTile({ public_url: "https://f7.example.com/", method: "cloudflare", reachable: true }),
    { method: "Cloudflare", status: "Connected", tone: "positive", host: "f7.example.com" },
  );
  assert.equal(remoteTile({ public_url: "https://x.y", method: "tailscale", reachable: false }).status, "Not reachable");
  assert.equal(remoteTile({ public_url: "https://x.y", method: "tailscale", reachable: false }).tone, "warning");
  assert.equal(remoteTile({ public_url: null, method: null, reachable: null }).status, "Off");
});

test("streaming tile: counts direct and transcode, and distinct people", () => {
  const sessions: SessionLike[] = ["u1", "u1", "u2"].map((u, i) => ({
    id: `s${i}`,
    user_id: u,
    username: u,
    display_name: u,
    device_label: null,
    client_type: "pwa",
    created_at: "2026-10-17T10:00:00Z",
    last_seen_at: null,
    expires_at: "2026-11-17T10:00:00Z",
  }));
  const tile = streamingTile(
    [transcode({ id: "a", direct_play: true, speed: null }), transcode({ id: "b" }), transcode({ id: "c" })],
    sessions,
  );
  assert.equal(tile.count, 3);
  assert.equal(tile.direct, 1);
  assert.equal(tile.transcode, 2);
  assert.equal(tile.people, 2);
  assert.equal(tile.summary, "1 direct play · 2 transcode");
  assert.equal(tile.peopleText, "2 people signed in");
  assert.equal(streamingTile([], sessions.slice(0, 1)).peopleText, "1 person signed in");
});

test("stream lines: DIRECT tag, variant and speed, and the slow flag", () => {
  const lines = streamLines(
    [
      transcode({ id: "a", direct_play: true, speed: null }),
      transcode({ id: "b", below_realtime_sec: 45 }),
    ],
    NOW,
  );
  assert.equal(lines[0].tag, "DIRECT");
  assert.equal(lines[0].slow, false);
  assert.equal(lines[1].tag, "720p · 0.82x");
  assert.equal(lines[1].slow, true);
  assert.equal(lines[1].initial, "J");
  assert.equal(lines[1].started, "Started 5 minutes ago");
});

test("library tile: scanning, failed, idle", () => {
  const running = scanRowsWith({
    state: "running",
    finished_at: null,
    scope: null,
    libraries: { movies: { state: "running", total: 10, seen: 4 } },
    last_error: null,
  });
  const tile = libraryTile(running, "2026-10-17T11:00:00Z", NOW);
  assert.equal(tile.state, "Scanning");
  assert.equal(tile.tone, "warning");
  assert.match(tile.detail, /Movies/);
  assert.equal(tile.lastSync, "Last sync 1 hour ago");

  const failed = scanRowsWith({
    state: "idle",
    finished_at: "2026-10-17T11:00:00Z",
    scope: null,
    libraries: { movies: { state: "failed" } },
    last_error: null,
  });
  assert.equal(libraryTile(failed, null, NOW).state, "Failed");
  assert.equal(libraryTile(failed, null, NOW).tone, "danger");
  assert.equal(libraryTile(failed, null, NOW).lastSync, "Last sync never");

  const idle = scanRowsWith({
    state: "idle",
    finished_at: "2026-10-17T11:00:00Z",
    scope: null,
    libraries: { movies: { state: "done", seen: 3, added: 3 } },
    last_error: null,
  });
  assert.equal(libraryTile(idle, null, NOW).state, "Idle");
});

test("sign-in activity: a failed sign-in says so in words", () => {
  const lines = eventLines(
    [
      { id: "1", user_id: "u", username: "jon", event: "login_failed", ip: "10.0.0.2", user_agent: null, at: "2026-10-17T11:59:00Z" },
      { id: "2", user_id: "u", username: "jon", event: "login_success", ip: null, user_agent: null, at: "2026-10-17T11:00:00Z" },
      { id: "3", user_id: null, username: null, event: "passkey_login_failed", ip: null, user_agent: null, at: "2026-10-17T10:00:00Z" },
    ],
    NOW,
  );
  assert.equal(lines[0].text, "Failed sign-in for jon");
  assert.equal(lines[0].failed, true);
  assert.equal(lines[1].text, "Signed in: jon");
  assert.equal(lines[1].failed, false);
  assert.equal(lines[2].text, "Failed sign-in for unknown");
});

test("settings tiles: nine tiles in order with their one-line status", () => {
  const tiles = settingsTiles({
    users: [
      { id: "1", role: "admin" },
      { id: "2", role: "member" },
      { id: "3", role: "member" },
    ],
    folders: { libraries: [{ folders: [1, 2] }, { folders: [3] }, { folders: [] }] },
    scanSummary: { text: "Up to date", attention: false },
    metadata: { tmdb: { configured: false } },
    arr: {
      apps: [
        { app: "radarr", label: "Radarr", configured: true },
        { app: "sonarr", label: "Sonarr", configured: false },
        { app: "lidarr", label: "Lidarr", configured: true },
      ],
    },
    audio: { analyzed: 40, total: 100, pending: 60 },
    remote: { public_url: "https://x", method: "cloudflare", reachable: true },
    updates: {
      installed_version: "1.0.14",
      phone_app_version: null,
      latest_version: "1.0.14",
      update_available: false,
      checked_at: null,
      run: null,
    },
  });
  assert.deepEqual(tiles.map((t) => t.href), ADMIN_AREAS.map((a) => a.href));
  const by = Object.fromEntries(tiles.map((t) => [t.id, t]));
  assert.equal(by.users.status, "3 people · 1 admin");
  assert.equal(by["library-folders"].status, "3 folders");
  assert.equal(by.scans.status, "Up to date");
  assert.equal(by.metadata.status, "TMDB key missing");
  assert.equal(by.metadata.tone, "warning");
  assert.equal(by.arr.status, "Radarr, Lidarr connected");
  assert.equal(by["audio-analysis"].status, "40 of 100 tracks done");
  assert.equal(by["remote-access"].status, "Cloudflare, Connected");
  assert.equal(by.updates.status, "1.0.14, up to date");
  assert.equal(by.activity.status, "Sessions, sign-ins, play history");
});

test("settings tiles: sources that did not load leave a blank status, not a crash", () => {
  const tiles = settingsTiles({
    users: null, folders: null, scanSummary: null, metadata: null,
    arr: null, audio: null, remote: null, updates: null,
  });
  assert.equal(tiles.length, 10);
  assert.equal(tiles.find((t) => t.id === "users")?.status, "");
  assert.equal(tiles.find((t) => t.id === "activity")?.status, "Sessions, sign-ins, play history");
  assert.equal(
    settingsTiles({ users: null, folders: null, scanSummary: null, metadata: { tmdb: { configured: true } },
      arr: { apps: [] }, audio: { analyzed: 0, total: 0, pending: 0 }, remote: null, updates: null })
      .filter((t) => t.id === "metadata" || t.id === "arr" || t.id === "audio-analysis")
      .map((t) => t.status).join("|"),
    "TMDB connected|Not connected|No music to analyze",
  );
});

test("relative time", () => {
  assert.equal(relativeTime("2026-10-17T11:59:40Z", NOW), "just now");
  assert.equal(relativeTime("2026-10-17T11:59:00Z", NOW), "1 minute ago");
  assert.equal(relativeTime("2026-10-17T09:00:00Z", NOW), "3 hours ago");
  assert.equal(relativeTime("2026-10-15T12:00:00Z", NOW), "2 days ago");
  assert.equal(relativeTime(null, NOW), "never");
  assert.equal(relativeTime("garbage", NOW), "a while ago");
});

test("settings grid source lists every area's href (no drift from ADMIN_AREAS)", () => {
  const src = readFileSync(new URL("../components/admin/SettingsGrid.tsx", import.meta.url), "utf8");
  for (const area of ADMIN_AREAS) {
    assert.ok(src.includes(`href: "${area.href}"`), area.href);
  }
});
