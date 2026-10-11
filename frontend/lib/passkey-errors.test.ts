// Run: node --test frontend/lib/passkey-errors.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { passkeyErrorMessage } from "./passkey-errors.ts";

test("passkey 401 never says username or password", () => {
  const m = passkeyErrorMessage(401, { detail: "passkey_verification_failed" });
  assert.match(m, /Passkey/);
  assert.doesNotMatch(m, /Username or password/);
});

test("passkey 5xx uses passkey wording, not the generic one", () => {
  const m = passkeyErrorMessage(500, null);
  assert.match(m, /Passkey/);
  assert.doesNotMatch(m, /bad time/);
});

test("400 and 429 are distinct", () => {
  assert.match(passkeyErrorMessage(400, { detail: "invalid_credential" }), /could not read/);
  assert.match(passkeyErrorMessage(429, { detail: "too_many_attempts" }), /Too many/);
});
