// Run: node --test scripts/npm_audit_gate.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { HARD_EXPIRY, evaluate, loadExceptions, main, parseAdvisories } from "./npm_audit_gate.mjs";

const advisory = (source, name, severity, ghsa) => ({
  source,
  name,
  severity,
  title: `${name} problem`,
  url: `https://github.com/advisories/${ghsa}`,
  range: "<=1.0.0",
});

const REPORT = {
  auditReportVersion: 2,
  vulnerabilities: {
    braces: { via: [advisory(1, "braces", "high", "GHSA-aaaa-bbbb-cccc")] },
    // Affected only through braces: a string in `via` is not an advisory.
    micromatch: { via: ["braces"] },
    "image-size": {
      via: [
        advisory(2, "image-size", "high", "GHSA-dddd-eeee-ffff"),
        advisory(3, "image-size", "high", "GHSA-gggg-hhhh-iiii"),
      ],
    },
    postcss: { via: [advisory(4, "postcss", "moderate", "GHSA-jjjj-kkkk-llll")] },
    // The same advisory reported under a second package is counted once.
    "other-pkg": { via: [advisory(1, "braces", "high", "GHSA-aaaa-bbbb-cccc")] },
  },
};

const good = (extra = {}) => ({
  advisory: "GHSA-aaaa-bbbb-cccc",
  reason: "no patched release",
  scope: "build",
  expires: "2026-12-31",
  ...extra,
});

test("parseAdvisories keeps only real advisories, once each, with their severity", () => {
  const found = parseAdvisories(REPORT);
  assert.deepEqual(found.map((a) => a.id), [
    "GHSA-AAAA-BBBB-CCCC",
    "GHSA-DDDD-EEEE-FFFF",
    "GHSA-GGGG-HHHH-IIII",
    "GHSA-JJJJ-KKKK-LLLL",
  ]);
  assert.equal(found[0].package, "braces");
  assert.equal(found[3].severity, "moderate");
});

test("parseAdvisories copes with an empty or odd report", () => {
  assert.deepEqual(parseAdvisories({}), []);
  assert.deepEqual(parseAdvisories(null), []);
  assert.deepEqual(parseAdvisories({ vulnerabilities: { x: { via: [null, 7, "y"] } } }), []);
});

test("an unlisted high advisory fails the gate", () => {
  const verdict = evaluate(parseAdvisories(REPORT), [], "2026-10-12");
  assert.equal(verdict.failures.length, 3);
  assert.ok(verdict.failures.every((f) => f.why === "no exception listed"));
  assert.equal(verdict.ungated, 1, "the moderate one is counted, not gated");
});

test("a listed, unexpired exception passes, by advisory id", () => {
  const { exceptions, errors } = loadExceptions({
    exceptions: [
      good(),
      good({ advisory: "ghsa-dddd-eeee-ffff" }),
      good({ advisory: "GHSA-gggg-hhhh-iiii" }),
    ],
  });
  assert.deepEqual(errors, []);
  const verdict = evaluate(parseAdvisories(REPORT), exceptions, "2026-10-12");
  assert.equal(verdict.failures.length, 0);
  assert.equal(verdict.accepted.length, 3);
});

test("a package-level exception covers every advisory in that package", () => {
  const { exceptions } = loadExceptions({
    exceptions: [
      { package: "braces", reason: "r", scope: "build", expires: "2026-12-31" },
      { package: "image-size", reason: "r", scope: "build", expires: "2026-12-31" },
    ],
  });
  assert.equal(evaluate(parseAdvisories(REPORT), exceptions, "2026-10-12").failures.length, 0);
});

test("an expired exception stops covering the advisory", () => {
  const { exceptions } = loadExceptions({
    exceptions: [
      good({ expires: "2026-10-11" }),
      good({ advisory: "GHSA-dddd-eeee-ffff" }),
      good({ advisory: "GHSA-gggg-hhhh-iiii" }),
    ],
  });
  const verdict = evaluate(parseAdvisories(REPORT), exceptions, "2026-10-12");
  assert.equal(verdict.failures.length, 1);
  assert.match(verdict.failures[0].why, /expired on 2026-10-11/);
  assert.equal(verdict.failures[0].advisory.package, "braces");
});

test("the last day is still valid, the next day is not", () => {
  const { exceptions } = loadExceptions({ exceptions: [good({ expires: "2026-12-31" })] });
  const advisories = parseAdvisories({ vulnerabilities: { braces: REPORT.vulnerabilities.braces } });
  assert.equal(evaluate(advisories, exceptions, "2026-12-31").failures.length, 0);
  assert.equal(evaluate(advisories, exceptions, "2027-01-01").failures.length, 1);
});

test("an exception that matches nothing is reported as unused, not failed", () => {
  const { exceptions } = loadExceptions({ exceptions: [good({ advisory: "GHSA-zzzz-zzzz-zzzz" })] });
  const verdict = evaluate([], exceptions, "2026-10-12");
  assert.equal(verdict.failures.length, 0);
  assert.equal(verdict.unused.length, 1);
});

test("moderate and low advisories are not gated", () => {
  const advisories = parseAdvisories({
    vulnerabilities: { postcss: { via: [advisory(4, "postcss", "moderate", "GHSA-jjjj-kkkk-llll")] } },
  });
  assert.equal(evaluate(advisories, [], "2026-10-12").failures.length, 0);
});

test("a critical advisory is gated like a high one", () => {
  const advisories = parseAdvisories({
    vulnerabilities: { evil: { via: [advisory(9, "evil", "critical", "GHSA-crit-crit-crit")] } },
  });
  assert.equal(evaluate(advisories, [], "2026-10-12").failures.length, 1);
});

test("loadExceptions rejects a bad entry", () => {
  const cases = [
    [{ advisory: "GHSA-a", scope: "build", expires: "2026-12-31" }, /reason/],
    [{ advisory: "GHSA-a", reason: "r", expires: "2026-12-31" }, /scope/],
    [{ advisory: "GHSA-a", reason: "r", scope: "dev", expires: "2026-12-31" }, /scope/],
    [{ reason: "r", scope: "build", expires: "2026-12-31" }, /advisory/],
    [{ advisory: "GHSA-a", reason: "r", scope: "build" }, /expires/],
    [{ advisory: "GHSA-a", reason: "r", scope: "build", expires: "soon" }, /expires/],
    [{ advisory: "GHSA-a", reason: "r", scope: "build", expires: "2026-13-45" }, /expires/],
    [{ advisory: "GHSA-a", reason: "r", scope: "build", expires: "2027-01-07" }, /hard cap/],
  ];
  for (const [entry, pattern] of cases) {
    const { errors } = loadExceptions({ exceptions: [entry] });
    assert.ok(errors.some((e) => pattern.test(e)), `${JSON.stringify(entry)} should fail on ${pattern}`);
  }
  assert.ok(loadExceptions({}).errors.length > 0);
  assert.ok(loadExceptions({ exceptions: "no" }).errors.length > 0);
});

test("the hard cap itself is allowed", () => {
  assert.equal(HARD_EXPIRY, "2027-01-06");
  assert.deepEqual(loadExceptions({ exceptions: [good({ expires: HARD_EXPIRY })] }).errors, []);
});

test("every shipped exceptions file is valid, runtime or build, with a reason and a capped expiry", () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  for (const app of ["frontend", "mobile"]) {
    const doc = JSON.parse(fs.readFileSync(path.join(root, app, "npm-audit-exceptions.json"), "utf8"));
    const { exceptions, errors } = loadExceptions(doc);
    assert.deepEqual(errors, [], `${app}/npm-audit-exceptions.json`);
    for (const e of exceptions) {
      assert.ok(e.reason.length > 20, `${app}: ${e.advisory || e.package} needs a real reason`);
      assert.ok(e.expires <= HARD_EXPIRY);
    }
  }
});

test("main fails on an audit report with an unlisted high advisory and passes a clean one", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "npm-audit-gate-"));
  const dirty = path.join(dir, "dirty.json");
  const clean = path.join(dir, "clean.json");
  fs.writeFileSync(dirty, JSON.stringify({
    vulnerabilities: { sneaky: { via: [advisory(77, "sneaky", "high", "GHSA-not-listed-here")] } },
  }));
  fs.writeFileSync(clean, JSON.stringify({ vulnerabilities: {} }));
  const quiet = (fn) => {
    const { log, error } = console;
    console.log = () => {};
    console.error = () => {};
    try {
      return fn();
    } finally {
      console.log = log;
      console.error = error;
    }
  };
  assert.equal(quiet(() => main(["frontend", "--audit-json", dirty])), 1);
  assert.equal(quiet(() => main(["frontend", "--audit-json", clean])), 0);
  assert.equal(quiet(() => main(["mobile", "--audit-json", clean])), 0);
  assert.equal(quiet(() => main(["nope"])), 2);
});

test("main fails when the audit gives no usable report", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "npm-audit-gate-"));
  const broken = path.join(dir, "broken.json");
  fs.writeFileSync(broken, "not json");
  const { log, error } = console;
  console.log = () => {};
  console.error = () => {};
  try {
    assert.equal(main(["frontend", "--audit-json", broken]), 1);
  } finally {
    console.log = log;
    console.error = error;
  }
});
