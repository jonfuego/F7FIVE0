// node:test coverage for the shared Bearer resolution used by the BFF routes.
//
// Run: node --test frontend/lib/api.test.ts (helper lives in lib/auth-bearer.ts)
//
// The art proxy routes (app/api/admin/art and app/api/art) stream raw bodies
// so they cannot go through backend(), but they must attach the same Bearer
// and, crucially, answer 401 instead of calling the API with no Bearer. Both
// behaviours come from bearerFromCookieValue, which is pure and tested here.

import { test } from "node:test";
import assert from "node:assert/strict";
import { bearerFromCookieValue } from "./auth-bearer.ts";

test("bearerFromCookieValue builds the Authorization header from a cookie value", () => {
  assert.equal(bearerFromCookieValue("abc.def.ghi"), "Bearer abc.def.ghi");
});

test("bearerFromCookieValue returns null when the cookie is missing", () => {
  // undefined is what cookies().get(...)?.value yields with no cookie; the
  // route turns a null here into a 401 rather than a no-Bearer API call.
  assert.equal(bearerFromCookieValue(undefined), null);
  assert.equal(bearerFromCookieValue(null), null);
});

test("bearerFromCookieValue returns null for an empty cookie value", () => {
  assert.equal(bearerFromCookieValue(""), null);
});
