// node:test coverage for the first-run admin rules on the login page.
//
// Run: node --test frontend/lib/first-run.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createAdminError,
  loginView,
  serverPcAddress,
  validateNewAdmin,
} from "./first-run.ts";

test("a fresh server shows the create form on the server PC only", () => {
  assert.equal(loginView({ needs_admin: true, local: true }), "create-admin");
  assert.equal(loginView({ needs_admin: true, local: false }), "finish-on-server");
});

test("a server with an account, or any odd answer, keeps the sign-in form", () => {
  assert.equal(loginView({ needs_admin: false, local: true }), "signin");
  assert.equal(loginView(null), "signin");
  assert.equal(loginView({ detail: "Not Found" }), "signin");
  assert.equal(loginView({ needs_admin: "yes", local: true }), "signin");
});

test("new admin rules match the API", () => {
  assert.equal(validateNewAdmin("Admin", "longenough", "longenough"), null);
  assert.match(validateNewAdmin("ab", "longenough", "longenough") ?? "", /3 to 64/);
  assert.match(validateNewAdmin("has space", "longenough", "longenough") ?? "", /3 to 64/);
  assert.match(validateNewAdmin("admin", "short", "short") ?? "", /at least 8/);
  assert.match(validateNewAdmin("admin", "longenough", "different1") ?? "", /do not match/);
});

test("failures read as sentences, never codes", () => {
  assert.match(createAdminError(409, { detail: "setup_done" }), /Sign in instead/);
  assert.match(createAdminError(403, { detail: "setup_local_only" }), /PC where F7FIVE0 is installed/);
  assert.match(createAdminError(422, { detail: [] }), /Check the username/);
  const generic = createAdminError(500, null);
  assert.ok(!generic.includes("_"));
});

test("the server PC address keeps this page's port", () => {
  assert.equal(serverPcAddress("3001"), "http://localhost:3001");
  assert.equal(serverPcAddress("3101"), "http://localhost:3101");
  assert.equal(serverPcAddress(""), "http://localhost:3001");
  assert.equal(serverPcAddress("evil.example"), "http://localhost:3001");
});
