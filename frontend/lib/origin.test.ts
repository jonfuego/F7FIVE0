// node:test coverage for the request-origin helper (SEC-P1-1): hostile Host
// and X-Forwarded-Proto headers must not reach a redirect URL or a cookie.
//
// Run: node --test frontend/lib/origin.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildOrigin, requestProto, siteOriginFromHeaders } from "./origin.ts";

const PUB = "https://media.example.com";

test("a private LAN host is allowed through", () => {
  assert.equal(
    buildOrigin({ host: "192.168.1.20:3101", proto: "http" }),
    "http://192.168.1.20:3101",
  );
  assert.equal(buildOrigin({ host: "127.0.0.1:3001", proto: "http" }), "http://127.0.0.1:3001");
  assert.equal(buildOrigin({ host: "localhost:3001", proto: "http" }), "http://localhost:3001");
});

test("the configured public host is allowed", () => {
  assert.equal(
    buildOrigin({ host: "media.example.com", proto: "https" }, { publicOrigin: PUB }),
    "https://media.example.com",
  );
});

test("an unknown public host falls back to the configured origin", () => {
  assert.equal(
    buildOrigin({ host: "evil.com", proto: "https" }, { publicOrigin: PUB }),
    "https://media.example.com",
  );
});

test("a header-injected host is neutralised", () => {
  const out = buildOrigin({ host: "evil.com\r\nSet-Cookie: x=1", proto: "https" }, { publicOrigin: PUB });
  assert.ok(!out.includes("evil.com"));
  assert.ok(!out.includes("\n"));
  assert.equal(out, "https://media.example.com");
});

test("a comma-list host is rejected", () => {
  assert.equal(
    buildOrigin({ host: "evil.com, media.example.com", proto: "https" }, { publicOrigin: PUB }),
    "https://media.example.com",
  );
});

test("a non-http(s) scheme is dropped", () => {
  const out = buildOrigin({ host: "192.168.1.20", proto: "javascript" });
  assert.ok(out.startsWith("http://"));
  assert.equal(out, "http://192.168.1.20");
});

test("allowedHosts widens the allowlist", () => {
  assert.equal(
    buildOrigin({ host: "nas.lan", proto: "http" }, { allowedHosts: ["nas.lan"] }),
    "http://nas.lan",
  );
});

test("requestProto only reports https when the header says so", () => {
  assert.equal(requestProto(new Headers({ "x-forwarded-proto": "https" })), "https");
  assert.equal(requestProto(new Headers({ "x-forwarded-proto": "http" })), "http");
  assert.equal(requestProto(new Headers({ "x-forwarded-proto": "javascript" })), "http");
  assert.equal(requestProto(new Headers()), "http");
});

test("siteOriginFromHeaders prefers x-forwarded-host and allowlists it", () => {
  const safe = siteOriginFromHeaders(
    new Headers({ "x-forwarded-host": "192.168.1.20:3101", "x-forwarded-proto": "http" }),
  );
  assert.equal(safe, "http://192.168.1.20:3101");
});
