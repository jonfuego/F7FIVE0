// node:test coverage for the browser security headers and the cross-origin
// state-change guard (SEC-P1-5).
//
// Run: node --test frontend/lib/security-headers.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CONTENT_SECURITY_POLICY,
  isForbiddenCrossOrigin,
  securityHeaders,
} from "./security-headers.ts";

test("CSP locks down framing, objects and base URI", () => {
  assert.ok(CONTENT_SECURITY_POLICY.includes("frame-ancestors 'none'"));
  assert.ok(CONTENT_SECURITY_POLICY.includes("object-src 'none'"));
  assert.ok(CONTENT_SECURITY_POLICY.includes("base-uri 'self'"));
});

test("CSP allows what HLS and Cast need", () => {
  assert.ok(CONTENT_SECURITY_POLICY.includes("media-src 'self' blob:"));
  assert.ok(CONTENT_SECURITY_POLICY.includes("worker-src 'self' blob:"));
  assert.ok(CONTENT_SECURITY_POLICY.includes("www.gstatic.com"));
});

test("HSTS only over HTTPS", () => {
  assert.equal(securityHeaders({ https: false })["Strict-Transport-Security"], undefined);
  assert.ok(securityHeaders({ https: true })["Strict-Transport-Security"]);
  // The always-on headers are present either way.
  for (const h of ["Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"]) {
    assert.ok(securityHeaders({ https: false })[h], `${h} missing`);
  }
  assert.equal(securityHeaders({ https: false })["X-Content-Type-Options"], "nosniff");
});

const SELF = "https://media.example.com";

test("a cross-origin state-changing cookie request is forbidden", () => {
  assert.equal(
    isForbiddenCrossOrigin({ method: "POST", pathname: "/api/library/sync", origin: "https://evil.com", selfOrigin: SELF, hasBearer: false }),
    true,
  );
  assert.equal(
    isForbiddenCrossOrigin({ method: "DELETE", pathname: "/api/admin/users/1", origin: "https://evil.com", selfOrigin: SELF, hasBearer: false }),
    true,
  );
});

test("same-origin, no-origin, bearer, GET, and non-API are allowed", () => {
  // Same origin.
  assert.equal(isForbiddenCrossOrigin({ method: "POST", pathname: "/api/x", origin: SELF, selfOrigin: SELF, hasBearer: false }), false);
  // No Origin header (top-level nav / non-browser).
  assert.equal(isForbiddenCrossOrigin({ method: "POST", pathname: "/api/x", origin: null, selfOrigin: SELF, hasBearer: false }), false);
  // Bearer-authed native app.
  assert.equal(isForbiddenCrossOrigin({ method: "POST", pathname: "/api/x", origin: "https://evil.com", selfOrigin: SELF, hasBearer: true }), false);
  // Safe method.
  assert.equal(isForbiddenCrossOrigin({ method: "GET", pathname: "/api/x", origin: "https://evil.com", selfOrigin: SELF, hasBearer: false }), false);
  // Not an API path.
  assert.equal(isForbiddenCrossOrigin({ method: "POST", pathname: "/login", origin: "https://evil.com", selfOrigin: SELF, hasBearer: false }), false);
});
