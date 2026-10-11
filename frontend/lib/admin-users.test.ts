// node:test coverage for the Admin > Users row rules.
//
// Run: node --test frontend/lib/admin-users.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  OWN_ROW_REASON,
  errorMessage,
  isOwnRow,
  okMessage,
  ownRowReason,
  rowMessageFor,
  userActionErrorText,
} from "./admin-users.ts";

test("your own row is locked and says why", () => {
  assert.equal(isOwnRow("me", "me"), true);
  assert.equal(ownRowReason("me", "me"), OWN_ROW_REASON);
  assert.match(OWN_ROW_REASON, /own account/);
});

test("another user's row is not locked and has no reason", () => {
  assert.equal(isOwnRow("other", "me"), false);
  assert.equal(ownRowReason("other", "me"), null);
});

test("a message shows only on the row it belongs to", () => {
  const msg = errorMessage("u1", "HTTP 500");
  assert.equal(rowMessageFor(msg, "u1"), msg);
  assert.equal(rowMessageFor(msg, "u2"), null);
  assert.equal(rowMessageFor(null, "u1"), null);
});

test("ok and error messages carry their kind", () => {
  assert.equal(okMessage("u1", "Saved.").kind, "ok");
  assert.equal(errorMessage("u1", "Nope").kind, "error");
});

test("the last-admin guards and a missing user get plain wording", () => {
  assert.equal(
    userActionErrorText({ status: 409, detail: "cannot_disable_last_admin", message: "HTTP 409" }),
    "Cannot disable the last active admin.",
  );
  assert.equal(
    userActionErrorText({ status: 409, detail: "cannot_demote_last_admin", message: "HTTP 409" }),
    "Cannot demote the last active admin.",
  );
  assert.match(userActionErrorText({ status: 404, detail: "user_not_found" }), /no longer exists/);
});

test("a server error names the status and says nothing changed", () => {
  const text = userActionErrorText({ status: 500, detail: null, message: "HTTP 500" });
  assert.match(text, /HTTP 500/);
  assert.match(text, /Nothing was changed/);
});

test("other errors fall back to the message, then to the default", () => {
  assert.equal(userActionErrorText({ status: 422, detail: "x", message: "HTTP 422: x" }), "HTTP 422: x");
  assert.equal(userActionErrorText(new Error("Failed to fetch")), "Failed to fetch");
  assert.equal(userActionErrorText(undefined), "Something went wrong.");
  assert.equal(userActionErrorText("weird", "Password reset failed."), "Password reset failed.");
});
