// node:test coverage for the proxy forward-header builder (Fix A, criterion 18).
//
// The old proxy.ts did `new Headers(req.headers)` and copied EVERY inbound
// header, then set x-forwarded-host/proto from the RAW browser values. The
// backend trusts loopback for forwarded headers and Next IS the loopback peer,
// so a direct LAN browser could send CF-Connecting-IP / X-Forwarded-For (to
// forge an audit IP or slip the login throttle) and X-Forwarded-Host (to poison
// a signed URL host). buildForwardHeaders strips those unless the request came
// through our own front door (the shared x-f7five0-proxy secret), and it always
// sets x-forwarded-host / x-forwarded-proto from the allowlisted origin, never
// the raw header.
//
// Run: node --test frontend/lib/forward-headers.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildForwardHeaders } from "./forward-headers.ts";

// The allowlisted site origin the proxy derives through origin.ts. evil.example
// must never survive as the forwarded host.
const SITE_HOST = "192.168.1.20:3101";

function hostile(): Headers {
  const h = new Headers();
  h.set("cf-connecting-ip", "203.0.113.9");
  h.set("x-forwarded-for", "203.0.113.9");
  h.set("x-real-ip", "203.0.113.9");
  h.set("forwarded", "for=203.0.113.9;host=evil.example;proto=https");
  h.set("x-forwarded-host", "evil.example");
  h.set("x-forwarded-proto", "javascript");
  // A benign header should always survive untouched.
  h.set("accept", "application/json");
  return h;
}

test("untrusted request: client-IP headers are stripped", () => {
  const out = buildForwardHeaders(hostile(), {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
  });
  assert.equal(out.get("cf-connecting-ip"), null);
  assert.equal(out.get("x-forwarded-for"), null);
  assert.equal(out.get("x-real-ip"), null);
  assert.equal(out.get("forwarded"), null);
});

test("untrusted request: forwarded host is the allowlisted site, not evil.example", () => {
  const out = buildForwardHeaders(hostile(), {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
  });
  assert.equal(out.get("x-forwarded-host"), SITE_HOST);
  assert.notEqual(out.get("x-forwarded-host"), "evil.example");
});

test("untrusted request: forwarded proto is sanitised http/https, never javascript", () => {
  const out = buildForwardHeaders(hostile(), {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
  });
  assert.equal(out.get("x-forwarded-proto"), "http");
  assert.notEqual(out.get("x-forwarded-proto"), "javascript");
});

test("the trust-secret header never reaches the backend", () => {
  const h = hostile();
  h.set("x-f7five0-proxy", "the-shared-secret");
  const untrusted = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
  });
  assert.equal(untrusted.get("x-f7five0-proxy"), null);
  const trusted = buildForwardHeaders(h, {
    siteOrigin: `https://media.example.com`,
    proto: "https",
    trusted: true,
  });
  assert.equal(trusted.get("x-f7five0-proxy"), null);
});

test("benign headers pass through either way", () => {
  const out = buildForwardHeaders(hostile(), {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
  });
  assert.equal(out.get("accept"), "application/json");
});

test("trusted request: client-IP headers pass through (they are the real remote IP)", () => {
  const out = buildForwardHeaders(hostile(), {
    siteOrigin: "https://media.example.com",
    proto: "https",
    trusted: true,
  });
  // The front door (Caddy) is the real remote peer, so these are genuine.
  assert.equal(out.get("cf-connecting-ip"), "203.0.113.9");
  assert.equal(out.get("x-forwarded-for"), "203.0.113.9");
});

test("trusted request: forwarded host is STILL the allowlisted host, never evil.example", () => {
  const out = buildForwardHeaders(hostile(), {
    siteOrigin: "https://media.example.com",
    proto: "https",
    trusted: true,
  });
  assert.equal(out.get("x-forwarded-host"), "media.example.com");
  assert.notEqual(out.get("x-forwarded-host"), "evil.example");
  assert.equal(out.get("x-forwarded-proto"), "https");
});
