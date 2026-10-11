// node:test coverage for the refresh sign-out decision.
//
// Run: node --test frontend/lib/refresh-outcome.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clearsSessionOnBackendStatus,
  decideRefresh,
  retryDelayMs,
  runRefresh,
  type RefreshOutcome,
} from "./refresh-outcome.ts";

const res = (status: number): RefreshOutcome => ({ kind: "response", status });
const networkError: RefreshOutcome = { kind: "network-error" };
const timeout: RefreshOutcome = { kind: "timeout" };

test("401 signs out, even with retries left", () => {
  assert.equal(decideRefresh(res(401), 0), "sign-out");
  assert.equal(decideRefresh(res(401), 2), "sign-out");
});

test("2xx is success", () => {
  assert.equal(decideRefresh(res(200)), "refreshed");
  assert.equal(decideRefresh(res(204)), "refreshed");
});

for (const status of [500, 502, 503, 504, 530]) {
  test(`${status} does not sign out: retries, then keeps the session`, () => {
    assert.equal(decideRefresh(res(status), 0), "retry");
    assert.equal(decideRefresh(res(status), 1), "retry");
    assert.equal(decideRefresh(res(status), 2), "keep-session");
  });
}

test("a network error does not sign out: retries, then keeps the session", () => {
  assert.equal(decideRefresh(networkError, 0), "retry");
  assert.equal(decideRefresh(networkError, 1), "retry");
  assert.equal(decideRefresh(networkError, 2), "keep-session");
});

test("a timeout does not sign out: retries, then keeps the session", () => {
  assert.equal(decideRefresh(timeout, 0), "retry");
  assert.equal(decideRefresh(timeout, 2), "keep-session");
});

test("408 and 429 are treated as try again", () => {
  assert.equal(decideRefresh(res(408), 0), "retry");
  assert.equal(decideRefresh(res(429), 0), "retry");
  assert.equal(decideRefresh(res(429), 2), "keep-session");
});

test("other 4xx never sign out and are not retried", () => {
  for (const status of [400, 403, 404, 422]) {
    assert.equal(decideRefresh(res(status), 0), "keep-session", String(status));
  }
});

test("retry delays are 0.5 s then 1.5 s", () => {
  assert.equal(retryDelayMs(0), 500);
  assert.equal(retryDelayMs(1), 1500);
});

test("runRefresh retries a 503 twice with the backoff, then succeeds", async () => {
  const answers = [res(503), networkError, res(200)];
  const slept: number[] = [];
  const out = await runRefresh(
    async () => answers.shift()!,
    async (ms) => {
      slept.push(ms);
    },
  );
  assert.equal(out, "refreshed");
  assert.deepEqual(slept, [500, 1500]);
});

test("runRefresh gives up with keep-session after 3 tries, never sign-out", async () => {
  let calls = 0;
  const out = await runRefresh(
    async () => {
      calls += 1;
      return res(502);
    },
    async () => {},
  );
  assert.equal(out, "keep-session");
  assert.equal(calls, 3);
});

test("runRefresh stops at the first 401 with no retry", async () => {
  let calls = 0;
  const out = await runRefresh(
    async () => {
      calls += 1;
      return res(401);
    },
    async () => {},
  );
  assert.equal(out, "sign-out");
  assert.equal(calls, 1);
});

test("the BFF route clears cookies only for a backend 401", () => {
  assert.equal(clearsSessionOnBackendStatus(401), true);
  for (const status of [200, 400, 403, 422, 500, 502, 503, 504]) {
    assert.equal(clearsSessionOnBackendStatus(status), false, String(status));
  }
});
