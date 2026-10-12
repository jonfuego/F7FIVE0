// Run: node --test frontend/lib/login-errors.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatWait,
  isThrottled,
  loginErrorMessage,
  parseRetryAfter,
  remainingSeconds,
  retryAfterHeader,
  throttleMessage,
} from "./login-errors.ts";

test("parseRetryAfter reads whole seconds and nothing else", () => {
  assert.equal(parseRetryAfter("900"), 900);
  assert.equal(parseRetryAfter(" 42 "), 42);
  assert.equal(parseRetryAfter("1"), 1);
  assert.equal(parseRetryAfter("0"), null);
  assert.equal(parseRetryAfter("-5"), null);
  assert.equal(parseRetryAfter("1.5"), null);
  assert.equal(parseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT"), null);
  assert.equal(parseRetryAfter("soon"), null);
  assert.equal(parseRetryAfter(""), null);
  assert.equal(parseRetryAfter(null), null);
  assert.equal(parseRetryAfter(undefined), null);
});

test("retryAfterHeader passes a good value through and drops junk", () => {
  assert.equal(retryAfterHeader("317"), "317");
  assert.equal(retryAfterHeader(" 317 "), "317");
  assert.equal(retryAfterHeader("abc"), null);
  assert.equal(retryAfterHeader(null), null);
});

test("formatWait counts seconds under a minute and rounds minutes up", () => {
  assert.equal(formatWait(1), "1 second");
  assert.equal(formatWait(45), "45 seconds");
  assert.equal(formatWait(59), "59 seconds");
  assert.equal(formatWait(60), "1 minute");
  assert.equal(formatWait(61), "2 minutes");
  assert.equal(formatWait(125), "3 minutes");
  assert.equal(formatWait(900), "15 minutes");
  assert.equal(formatWait(0), "1 second");
  assert.equal(formatWait(0.2), "1 second");
});

test("throttleMessage says how long, in words", () => {
  assert.equal(throttleMessage(900), "Too many attempts. Try again in 15 minutes.");
  assert.equal(throttleMessage(30), "Too many attempts. Try again in 30 seconds.");
  assert.equal(throttleMessage(60), "Too many attempts. Try again in 1 minute.");
});

test("throttleMessage without a wait still reads like a sentence", () => {
  for (const missing of [null, undefined, 0, -3, Number.NaN]) {
    assert.equal(throttleMessage(missing), "Too many attempts. Try again in a few minutes.");
  }
});

test("a 429 never shows the raw code, with or without a wait", () => {
  const payload = { detail: "too_many_attempts" };
  for (const retry of [900, 12, 1, null, undefined]) {
    const m = loginErrorMessage(429, payload, retry);
    assert.doesNotMatch(m, /too_many_attempts/);
    assert.match(m, /^Too many attempts\. Try again in /);
  }
  assert.doesNotMatch(loginErrorMessage(200, payload), /too_many_attempts/);
  assert.doesNotMatch(loginErrorMessage(429, null), /too_many_attempts/);
});

test("the code alone is enough to be recognised as a lockout", () => {
  assert.equal(isThrottled(200, { detail: "too_many_attempts" }), true);
  assert.equal(isThrottled(429, null), true);
  assert.equal(isThrottled(401, { detail: "invalid_credentials" }), false);
});

test("the other sign-in errors keep their wording", () => {
  assert.equal(loginErrorMessage(401, { detail: "invalid_credentials" }), "Username or password is incorrect.");
  assert.equal(loginErrorMessage(400, { detail: "missing_credentials" }), "Fill in both username and password.");
  assert.match(loginErrorMessage(503, null), /bad time/);
  assert.equal(loginErrorMessage(418, { detail: "teapot" }), "teapot");
  assert.equal(loginErrorMessage(418, null), "Something went wrong.");
});

test("remainingSeconds counts down to zero and stops", () => {
  assert.equal(remainingSeconds(10_000, 0), 10);
  assert.equal(remainingSeconds(10_000, 9_001), 1);
  assert.equal(remainingSeconds(10_000, 10_000), 0);
  assert.equal(remainingSeconds(10_000, 12_000), 0);
});

test("the countdown message gets shorter as time passes", () => {
  const until = 1_000_000;
  assert.equal(throttleMessage(remainingSeconds(until, until - 600_000)), "Too many attempts. Try again in 10 minutes.");
  assert.equal(throttleMessage(remainingSeconds(until, until - 59_000)), "Too many attempts. Try again in 59 seconds.");
  assert.equal(throttleMessage(remainingSeconds(until, until - 1_000)), "Too many attempts. Try again in 1 second.");
});
