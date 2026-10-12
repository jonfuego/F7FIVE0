#!/usr/bin/env node
// CI gate: run `npm audit --omit=dev --json` for the web app or the phone app
// and fail on any high or critical advisory that is not listed (and unexpired)
// in <app>/npm-audit-exceptions.json. The npm twin of scripts/pip_audit_gate.py.
//
//   node scripts/npm_audit_gate.mjs frontend
//   node scripts/npm_audit_gate.mjs mobile
//
// Exceptions file shape:
//   { "exceptions": [
//       { "advisory": "GHSA-xxxx-xxxx-xxxx",   // or "package": "name" for every advisory in a package
//         "package": "name",                     // optional label when "advisory" is given
//         "reason": "why it is accepted for now",
//         "scope": "runtime" | "build",          // runtime = ships in the app; build = dev machine tooling
//         "expires": "YYYY-MM-DD" } ] }          // on or before 2027-01-06
//
// Rules, enforced here:
//   - every entry needs a reason, a scope, a real date, and an expiry no later
//     than HARD_EXPIRY;
//   - an expired entry stops matching, so the advisory fails the gate again and
//     forces a re-review;
//   - moderate and low advisories are counted, not gated;
//   - npm audit not answering (no network, registry down) fails the gate: a gate
//     that cannot run must not pass.
//
// Dev tooling that is not in `dependencies` is already out of scope
// (`--omit=dev`); Expo's build tools (Metro, the Expo CLI) are in `dependencies`,
// which is why they show up here and carry `build` exceptions.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const HARD_EXPIRY = "2027-01-06";
export const GATED = new Set(["high", "critical"]);
export const APPS = ["frontend", "mobile"];

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Pull the distinct advisories out of `npm audit --json` output (report
 * version 2). A vulnerability's `via` holds advisory objects (the real findings)
 * and strings (packages that are only affected through another package); only
 * the objects are advisories. */
export function parseAdvisories(report) {
  const found = new Map();
  const vulnerabilities = (report && report.vulnerabilities) || {};
  for (const [pkg, vuln] of Object.entries(vulnerabilities)) {
    for (const via of vuln.via || []) {
      if (!via || typeof via !== "object") continue;
      const url = String(via.url || "");
      const id = (url.split("/").pop() || String(via.source || "")).toUpperCase();
      if (!id) continue;
      if (!found.has(id)) {
        found.set(id, {
          id,
          package: via.name || pkg,
          severity: String(via.severity || "").toLowerCase(),
          title: via.title || "",
          range: via.range || "",
        });
      }
    }
  }
  return [...found.values()].sort((a, b) => a.id.localeCompare(b.id));
}

/** Validate an exceptions document. Returns { exceptions, errors }. */
export function loadExceptions(doc) {
  const errors = [];
  const list = doc && Array.isArray(doc.exceptions) ? doc.exceptions : null;
  if (!list) return { exceptions: [], errors: ['exceptions file needs an "exceptions" array'] };
  const exceptions = [];
  list.forEach((e, i) => {
    const label = `exceptions[${i}] (${(e && (e.advisory || e.package)) || "?"})`;
    if (!e || typeof e !== "object") return errors.push(`${label}: not an object`);
    if (!e.advisory && !e.package) errors.push(`${label}: needs an "advisory" id or a "package"`);
    if (!e.reason || !String(e.reason).trim()) errors.push(`${label}: needs a reason`);
    if (e.scope !== "runtime" && e.scope !== "build") errors.push(`${label}: scope must be "runtime" or "build"`);
    if (!DATE.test(String(e.expires || "")) || Number.isNaN(Date.parse(`${e.expires}T00:00:00Z`))) {
      errors.push(`${label}: expires must be a YYYY-MM-DD date`);
    } else if (e.expires > HARD_EXPIRY) {
      errors.push(`${label}: expires ${e.expires} is after the hard cap ${HARD_EXPIRY}`);
    }
    exceptions.push({
      advisory: e.advisory ? String(e.advisory).toUpperCase() : null,
      package: e.package ? String(e.package) : null,
      reason: String(e.reason || ""),
      scope: e.scope,
      expires: String(e.expires || ""),
    });
  });
  return { exceptions, errors };
}

function matches(exception, advisory) {
  if (exception.advisory) return exception.advisory === advisory.id;
  return exception.package === advisory.package;
}

/** Decide the gate. `today` is YYYY-MM-DD. */
export function evaluate(advisories, exceptions, today) {
  const failures = [];
  const accepted = [];
  const used = new Set();
  let ungated = 0;
  for (const adv of advisories) {
    if (!GATED.has(adv.severity)) {
      ungated += 1;
      continue;
    }
    const hits = exceptions.filter((e) => matches(e, adv));
    const live = hits.find((e) => e.expires >= today);
    if (live) {
      used.add(live);
      accepted.push({ advisory: adv, exception: live });
    } else if (hits.length) {
      hits.forEach((h) => used.add(h));
      failures.push({ advisory: adv, why: `its exception expired on ${hits[0].expires}; re-review it` });
    } else {
      failures.push({ advisory: adv, why: "no exception listed" });
    }
  }
  const unused = exceptions.filter((e) => !used.has(e) && !advisories.some((a) => matches(e, a)));
  return { failures, accepted, unused, ungated };
}

function runAudit(appDir) {
  const result = spawnSync("npm", ["audit", "--omit=dev", "--json"], {
    cwd: appDir,
    encoding: "utf8",
    shell: process.platform === "win32",
    maxBuffer: 64 * 1024 * 1024,
  });
  // npm exits non-zero when it finds anything; the JSON is still on stdout.
  try {
    const report = JSON.parse(result.stdout);
    if (report && report.error) throw new Error(report.error.summary || report.error.code || "npm audit error");
    return report;
  } catch (err) {
    throw new Error(`npm audit gave no usable JSON in ${appDir}: ${err.message}\n${result.stderr || ""}`);
  }
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

export function main(argv) {
  const app = argv[0];
  if (!APPS.includes(app)) {
    console.error(`usage: node scripts/npm_audit_gate.mjs <${APPS.join("|")}> [--audit-json file] [--today YYYY-MM-DD]`);
    return 2;
  }
  const flag = (name) => {
    const i = argv.indexOf(name);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const appDir = path.join(root, app);
  const exceptionsPath = path.join(appDir, "npm-audit-exceptions.json");

  let doc;
  try {
    doc = JSON.parse(fs.readFileSync(exceptionsPath, "utf8"));
  } catch (err) {
    console.error(`${app}: cannot read ${exceptionsPath}: ${err.message}`);
    return 1;
  }
  const { exceptions, errors } = loadExceptions(doc);
  if (errors.length) {
    console.error(`${app}: npm-audit-exceptions.json is invalid:`);
    errors.forEach((e) => console.error(`  - ${e}`));
    return 1;
  }

  let report;
  try {
    const file = flag("--audit-json");
    report = file ? JSON.parse(fs.readFileSync(file, "utf8")) : runAudit(appDir);
  } catch (err) {
    console.error(`${app}: ${err.message}`);
    return 1;
  }

  const advisories = parseAdvisories(report);
  const verdict = evaluate(advisories, exceptions, flag("--today") || today());

  for (const { advisory: a, exception: e } of verdict.accepted) {
    console.log(`excepted [${e.scope}] ${a.severity} ${a.id} ${a.package} until ${e.expires}: ${e.reason}`);
  }
  for (const e of verdict.unused) {
    console.log(`note: exception ${e.advisory || e.package} matches nothing now; remove it`);
  }
  if (verdict.ungated) console.log(`${verdict.ungated} moderate or low advisory(ies) not gated`);
  if (verdict.failures.length) {
    for (const { advisory: a, why } of verdict.failures) {
      console.error(`FAIL ${a.severity} ${a.id} ${a.package} (${a.range}): ${a.title} -- ${why}`);
    }
    console.error(`${app}: ${verdict.failures.length} high or critical advisory(ies) need a fix or a reviewed exception in ${app}/npm-audit-exceptions.json`);
    return 1;
  }
  console.log(`npm audit gate OK (${app}): no high or critical advisory outside the unexpired exception list.`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main(process.argv.slice(2)));
}
