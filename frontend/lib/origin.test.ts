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

// Item 1 (batch 5): the web process now gets PUBLIC_URL / APP_ALLOWED_HOSTS so
// a public host, a LAN machine name and an allowlisted host all survive, while
// a hostile dotted host still falls back to the configured origin.
test("a LAN machine name (single label) is allowed by rule", () => {
  // Reached at http://mediabox:3001 by its Windows computer name, no config.
  assert.equal(buildOrigin({ host: "mediabox:3001", proto: "http" }), "http://mediabox:3001");
  assert.equal(buildOrigin({ host: "mediabox", proto: "http" }), "http://mediabox");
});

test("an mDNS .local name is allowed by rule", () => {
  assert.equal(buildOrigin({ host: "mediabox.local:3001", proto: "http" }), "http://mediabox.local:3001");
});

test("a hostile dotted host is still rejected with a public URL set", () => {
  assert.equal(
    buildOrigin({ host: "evil.example", proto: "https" }, { publicOrigin: PUB }),
    "https://media.example.com",
  );
});

test("APP_ALLOWED_HOSTS env wiring lets a configured host through", () => {
  const prevPub = process.env.PUBLIC_URL;
  const prevAllowed = process.env.APP_ALLOWED_HOSTS;
  process.env.PUBLIC_URL = PUB;
  process.env.APP_ALLOWED_HOSTS = "nas.internal.example";
  try {
    // Allowed because it is in APP_ALLOWED_HOSTS.
    assert.equal(
      siteOriginFromHeaders(new Headers({ "x-forwarded-host": "nas.internal.example", "x-forwarded-proto": "http" })),
      "http://nas.internal.example",
    );
    // The configured public host is allowed.
    assert.equal(
      siteOriginFromHeaders(new Headers({ "x-forwarded-host": "media.example.com", "x-forwarded-proto": "https" })),
      "https://media.example.com",
    );
    // A hostile dotted host not in the list falls back to PUBLIC_URL.
    assert.equal(
      siteOriginFromHeaders(new Headers({ "x-forwarded-host": "evil.example", "x-forwarded-proto": "https" })),
      "https://media.example.com",
    );
  } finally {
    if (prevPub === undefined) delete process.env.PUBLIC_URL;
    else process.env.PUBLIC_URL = prevPub;
    if (prevAllowed === undefined) delete process.env.APP_ALLOWED_HOSTS;
    else process.env.APP_ALLOWED_HOSTS = prevAllowed;
  }
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
