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
import { buildForwardHeaders, PEER_HEADER, TRUST_HEADER } from "./forward-headers.ts";

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

// ---------------------------------------------------------------------------
// Fix B (criterion 4/5): the launcher stamps the real socket peer as
// x-f7five0-peer and sets F7FIVE0_LAUNCHER. The proxy passes the raw peer value
// and launcherActive flag in here; this helper decides trust from the peer.
// ---------------------------------------------------------------------------

// (i) LAN peer with hostile client-IP headers: x-forwarded-for becomes the real
// peer, forged cf-connecting-ip is dropped.
test("Fix B: LAN peer overrides a forged client IP", () => {
  const h = hostile();
  h.set(PEER_HEADER, "192.168.0.38");
  const out = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "192.168.0.38",
    launcherActive: true,
  });
  assert.equal(out.get("x-forwarded-for"), "192.168.0.38");
  assert.equal(out.get("cf-connecting-ip"), null);
  assert.equal(out.get("x-real-ip"), null);
  assert.equal(out.get("forwarded"), null);
});

// (i b) IPv4-mapped IPv6 peer is unwrapped to the bare v4 literal.
test("Fix B: IPv4-mapped IPv6 peer is unwrapped", () => {
  const h = hostile();
  const out = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "::ffff:192.168.0.38",
    launcherActive: true,
  });
  assert.equal(out.get("x-forwarded-for"), "192.168.0.38");
  assert.equal(out.get("cf-connecting-ip"), null);
});

// (ii) loopback peer (a local front door over loopback) keeps its forwarded IP.
test("Fix B: loopback peer keeps its client-IP headers (local front door)", () => {
  const h = new Headers();
  h.set("cf-connecting-ip", "203.0.113.9");
  h.set("x-forwarded-for", "203.0.113.9");
  const out = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "127.0.0.1",
    launcherActive: true,
  });
  assert.equal(out.get("cf-connecting-ip"), "203.0.113.9");
  assert.equal(out.get("x-forwarded-for"), "203.0.113.9");
});

// (ii b) IPv4-mapped loopback peer is also treated as loopback.
test("Fix B: ::ffff:127.0.0.1 peer is loopback and passes through", () => {
  const h = new Headers();
  h.set("cf-connecting-ip", "203.0.113.9");
  const out = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "::ffff:127.0.0.1",
    launcherActive: true,
  });
  assert.equal(out.get("cf-connecting-ip"), "203.0.113.9");
});

// (iii) no launcher signal: a CLIENT-SENT peer header must not be honoured, and
// the client-IP headers are stripped (fail closed -> backend records loopback).
test("Fix B: no launcher signal, a client-sent peer is NOT honoured", () => {
  const h = hostile();
  h.set(PEER_HEADER, "192.168.0.38"); // a client trying to forge the peer
  const out = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "192.168.0.38",
    launcherActive: false,
  });
  assert.equal(out.get("cf-connecting-ip"), null);
  assert.equal(out.get("x-forwarded-for"), null);
  assert.equal(out.get("x-real-ip"), null);
  assert.equal(out.get("forwarded"), null);
});

// (iv) X-Forwarded-Host is never honoured from the raw header, even with a peer.
test("Fix B: X-Forwarded-Host: evil.example never becomes the forwarded host", () => {
  const h = hostile();
  const out = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "192.168.0.38",
    launcherActive: true,
  });
  assert.equal(out.get("x-forwarded-host"), SITE_HOST);
  assert.notEqual(out.get("x-forwarded-host"), "evil.example");
});

// (v) the peer header and the secret header are absent from the output.
test("Fix B: the peer header and the trust-secret header never reach the backend", () => {
  const h = hostile();
  h.set(PEER_HEADER, "192.168.0.38");
  h.set(TRUST_HEADER, "the-shared-secret");
  const lan = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "192.168.0.38",
    launcherActive: true,
  });
  assert.equal(lan.get(PEER_HEADER), null);
  assert.equal(lan.get(TRUST_HEADER), null);
  const loop = buildForwardHeaders(h, {
    siteOrigin: `http://${SITE_HOST}`,
    proto: "http",
    trusted: false,
    peer: "127.0.0.1",
    launcherActive: true,
  });
  assert.equal(loop.get(PEER_HEADER), null);
  assert.equal(loop.get(TRUST_HEADER), null);
});

// A trusted (Caddy front-door secret) hop still wins over the peer logic: the
// genuine forwarded IP passes even though the peer would be loopback.
test("Fix B: a trusted secret hop keeps its forwarded IP regardless of peer", () => {
  const h = hostile();
  const out = buildForwardHeaders(h, {
    siteOrigin: "https://media.example.com",
    proto: "https",
    trusted: true,
    peer: "127.0.0.1",
    launcherActive: true,
  });
  assert.equal(out.get("cf-connecting-ip"), "203.0.113.9");
  assert.equal(out.get("x-forwarded-for"), "203.0.113.9");
});
