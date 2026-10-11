// node:test coverage for the *arr webhook address choices.
//
// Run: node --test frontend/lib/arr-webhook.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { isLoopbackOrigin, webhookBases, webhookUrl } from "./arr-webhook.ts";

const lan = { label: "Home network", url: "http://192.168.1.20:3001" };
const pub = { label: "Public address", url: "https://media.example.com" };

test("the address in use comes first, duplicates dropped", () => {
  assert.deepEqual(webhookBases("http://192.168.1.20:3001", [lan, pub]).map((b) => b.url), [
    "http://192.168.1.20:3001",
    "https://media.example.com",
  ]);
  assert.deepEqual(webhookBases("https://media.example.com/", [lan, pub]).map((b) => b.url), [
    "https://media.example.com",
    "http://192.168.1.20:3001",
  ]);
});

test("a loopback address goes after the ones a LAN app can reach", () => {
  assert.deepEqual(webhookBases("http://localhost:3001", [lan, pub]).map((b) => b.url), [
    "http://192.168.1.20:3001",
    "https://media.example.com",
    "http://localhost:3001",
  ]);
  assert.deepEqual(webhookBases("http://127.0.0.1:3001", []).map((b) => b.url), ["http://127.0.0.1:3001"]);
});

test("loopback detection", () => {
  assert.equal(isLoopbackOrigin("http://localhost:3001"), true);
  assert.equal(isLoopbackOrigin("http://127.0.0.1:3001"), true);
  assert.equal(isLoopbackOrigin("http://[::1]:3001"), true);
  assert.equal(isLoopbackOrigin("http://192.168.1.20:3001"), false);
  assert.equal(isLoopbackOrigin("not a url"), false);
});

test("no browser origin falls back to what the server knows", () => {
  assert.deepEqual(webhookBases("", [lan]).map((b) => b.url), ["http://192.168.1.20:3001"]);
  assert.deepEqual(webhookBases("", []), []);
});

test("webhookUrl joins cleanly", () => {
  assert.equal(webhookUrl("http://x:3001/", "/api/webhooks/radarr"), "http://x:3001/api/webhooks/radarr");
  assert.equal(webhookUrl("http://x:3001", "api/webhooks/lidarr"), "http://x:3001/api/webhooks/lidarr");
});
