#!/usr/bin/env node
/* `npm run verify` -> runs tsc, eslint and jest, writing:
 *   reports/tsc.log     (typecheck output; must contain no "error TS" line)
 *   reports/eslint.log  (lint output)
 *   reports/jest.json   (jest --json result)
 * Exits non-zero if tsc or jest fail so CI/local both see a red result, but
 * always writes all three logs first so the reports reflect the real run.
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const reports = path.join(root, "reports");
fs.mkdirSync(reports, { recursive: true });

function run(cmd, args) {
  const r = spawnSync(cmd, args, {
    cwd: root,
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  return { out: (r.stdout || "") + (r.stderr || ""), code: r.status };
}

console.log("[verify] tsc --noEmit");
const tsc = run("npx", ["tsc", "--noEmit", "--pretty", "false"]);
fs.writeFileSync(path.join(reports, "tsc.log"), tsc.out || "(no tsc output)\n");

console.log("[verify] eslint");
const eslint = run("npx", ["eslint", ".", "--ext", ".ts,.tsx"]);
fs.writeFileSync(path.join(reports, "eslint.log"), eslint.out || "(no eslint output)\n");

console.log("[verify] jest --json");
const jest = run("npx", [
  "jest",
  "--json",
  "--outputFile",
  path.join("reports", "jest.json"),
]);
// jest prints a human summary to stderr; keep it visible.
process.stdout.write(jest.out);

const tscErrors = (tsc.out.match(/error TS\d+/g) || []).length;
console.log(`[verify] tsc error TS lines: ${tscErrors}`);
console.log(`[verify] tsc exit=${tsc.code} eslint exit=${eslint.code} jest exit=${jest.code}`);

const failed = tscErrors > 0 || jest.code !== 0;
process.exit(failed ? 1 : 0);
