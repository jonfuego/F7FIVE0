// node:test coverage for the release notes Markdown reader.
//
// Run: node --test frontend/lib/release-notes.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { RELEASE_NOTES_MARKER, parseInline, parseReleaseNotes, releasePageUrl, whatsNew } from "./release-notes.ts";

test("bold, code and links become their own pieces", () => {
  assert.deepEqual(parseInline("choose **More info**, then `Run anyway`."), [
    { kind: "text", text: "choose " },
    { kind: "bold", text: "More info" },
    { kind: "text", text: ", then " },
    { kind: "code", text: "Run anyway" },
    { kind: "text", text: "." },
  ]);
  assert.deepEqual(parseInline("Full guide: [INSTALL.md](https://github.com/jonfuego/F7FIVE0/blob/v1.0.13/INSTALL.md)."), [
    { kind: "text", text: "Full guide: " },
    { kind: "link", text: "INSTALL.md", href: "https://github.com/jonfuego/F7FIVE0/blob/v1.0.13/INSTALL.md" },
    { kind: "text", text: "." },
  ]);
});

test("a link that is not http(s) stays plain text", () => {
  const pieces = parseInline("[click](javascript:alert)");
  assert.equal(pieces.some((p) => p.kind === "link"), false);
  assert.equal(pieces.map((p) => ("text" in p ? p.text : "")).join(""), "click");
});

test("HTML in the notes is only ever text", () => {
  const blocks = parseReleaseNotes("<script>alert(1)</script>");
  assert.deepEqual(blocks, [{ kind: "paragraph", content: [{ kind: "text", text: "<script>alert(1)</script>" }] }]);
});

test("headings, lists and paragraphs", () => {
  const md = [
    "## What's new",
    "",
    "- Faster updates",
    "- Podcast resume",
    "  keeps its place",
    "",
    "1. Download",
    "2. Run",
    "",
    "Setup needs a 64-bit PC.",
    "It also needs an admin account.",
  ].join("\r\n");
  const blocks = parseReleaseNotes(md);
  assert.equal(blocks.length, 4);
  assert.deepEqual(blocks[0], { kind: "heading", level: 2, content: [{ kind: "text", text: "What's new" }] });
  assert.deepEqual(blocks[1], {
    kind: "list",
    ordered: false,
    items: [[{ kind: "text", text: "Faster updates" }], [{ kind: "text", text: "Podcast resume keeps its place" }]],
  });
  assert.equal(blocks[2].kind === "list" && blocks[2].ordered, true);
  assert.deepEqual(blocks[3], {
    kind: "paragraph",
    content: [{ kind: "text", text: "Setup needs a 64-bit PC. It also needs an admin account." }],
  });
});

test("empty notes give no blocks", () => {
  assert.deepEqual(parseReleaseNotes(""), []);
  assert.deepEqual(parseReleaseNotes("\n\n"), []);
});

// The v1.0.23 release page as GitHub served it (CRLF and all): the download
// guide, then the generated list, then the Full Changelog line.
const OLD_1_0_23 = "## Which file do I need?\n\n| File | What it is |\n|---|---|\n| `F7FIVE0-Setup-1.0.23.exe` | **The Windows installer. Most people need only this file.** Run it on the PC that will be your media server. |\n| `F7FIVE0-1.0.23.apk` | The Android phone app. It installs on a phone, not on Windows. Easier: once your server is running, sign in from your phone's browser and use **Account > Download for Android**. |\n| `F7FIVE0-1.0.23.zip` | The same server files without the wizard, for installing from PowerShell. See \"Installing without the wizard\" in INSTALL.md. |\n| `SHA256SUMS.txt` | Checksums for the installer and the zip. |\n| `sbom-*.cdx.json` | Software bill of materials. |\n\nSetup needs a 64-bit Windows 10 (1809 or newer) or Windows 11 PC, an administrator account, and an internet connection. Setup is not code-signed yet, so Windows may show \"Windows protected your PC\": choose **More info**, then **Run anyway**. Full guide: [INSTALL.md](https://github.com/jonfuego/F7FIVE0/blob/v1.0.23/INSTALL.md).\n\n[Code signing policy](https://github.com/jonfuego/F7FIVE0/blob/v1.0.23/docs/code-signing-policy.md) | [Privacy](https://github.com/jonfuego/F7FIVE0/blob/v1.0.23/PRIVACY.md)\n\n## What's Changed\n* fix(setup): PostgreSQL and NSSM are pinned downloads, never winget by @jonfuego in https://github.com/jonfuego/F7FIVE0/pull/24\n\n\n**Full Changelog**: https://github.com/jonfuego/F7FIVE0/compare/v1.0.22...v1.0.23";

const GUIDE = [
  "## Which file do I need?",
  "",
  "| File | What it is |",
  "|---|---|",
  "| `F7FIVE0-Setup-1.0.24.exe` | **The Windows installer.** |",
  "| `SHA256SUMS.txt` | Checksums. |",
  "",
  "Setup needs a 64-bit Windows 10 PC.",
].join("\n");

test("a page with the marker shows only what is above it", () => {
  const body = ["- Faster scans", "- Podcast resume keeps its place", "", RELEASE_NOTES_MARKER, "", GUIDE, "", "**Full Changelog**: https://x"].join("\r\n");
  assert.equal(whatsNew(body), "- Faster scans\n- Podcast resume keeps its place");
});

test("an older page loses the download guide and the Full Changelog line", () => {
  const text = whatsNew(OLD_1_0_23);
  assert.equal(text, "## What's Changed\n* fix(setup): PostgreSQL and NSSM are pinned downloads, never winget");
  for (const gone of ["Which file", "SmartScreen", "Run anyway", "Full Changelog", "SHA256SUMS", "|", "@jonfuego"]) {
    assert.equal(text.includes(gone), false, gone);
  }
});

test("an older page with only the guide has no notes", () => {
  assert.equal(whatsNew(GUIDE + "\n\n\n**Full Changelog**: https://github.com/jonfuego/F7FIVE0/compare/v1.0.17...v1.0.18"), "");
  assert.equal(whatsNew(GUIDE + "\n\n## What's Changed\n\n**Full Changelog**: https://x"), "");
  assert.equal(whatsNew(RELEASE_NOTES_MARKER + "\n" + GUIDE), "");
  assert.equal(whatsNew(""), "");
  assert.equal(whatsNew(null), "");
});

test("notes without a guide stay as they are", () => {
  assert.equal(whatsNew("What changed\n- one thing\n- another"), "What changed\n- one thing\n- another");
});

test("a table becomes rows and cells, not one run-on paragraph", () => {
  const blocks = parseReleaseNotes(GUIDE);
  assert.deepEqual(blocks.map((b) => b.kind), ["heading", "table", "paragraph"]);
  const table = blocks[1];
  assert.ok(table.kind === "table");
  assert.deepEqual(table.header, [[{ kind: "text", text: "File" }], [{ kind: "text", text: "What it is" }]]);
  assert.equal(table.rows.length, 2);
  assert.deepEqual(table.rows[0][0], [{ kind: "code", text: "F7FIVE0-Setup-1.0.24.exe" }]);
  assert.deepEqual(table.rows[0][1], [{ kind: "bold", text: "The Windows installer." }]);
});

test("table rows line up with the header, and an escaped pipe stays in its cell", () => {
  const blocks = parseReleaseNotes("| a | b |\n| :-- | --: |\n| 1 |\n| x \\| y | z | extra |");
  assert.ok(blocks[0].kind === "table");
  const rows = blocks[0].rows.map((r) => r.map((c) => c.map((p) => ("text" in p ? p.text : "")).join("")));
  assert.deepEqual(rows, [["1", ""], ["x | y", "z"]]);
});

test("a pipe line without a rule under it is plain text", () => {
  assert.deepEqual(parseReleaseNotes("| not a table |"), [
    { kind: "paragraph", content: [{ kind: "text", text: "| not a table |" }] },
  ]);
});

test("release page links", () => {
  assert.equal(releasePageUrl("1.0.23"), "https://github.com/jonfuego/F7FIVE0/releases/tag/v1.0.23");
  assert.equal(releasePageUrl("../x"), "https://github.com/jonfuego/F7FIVE0/releases");
});

test("no HTML comment opener survives, even nested or unclosed", () => {
  assert.equal(whatsNew("- Fix\n<!-- note -->\n- More"), "- Fix\n\n- More");
  for (const body of ["<!<!---->--- Fix", "- Fix\n<!<!-- x -->-- y -->", "- Fix <!<!-- a -->-- b -->", "- Fix <!-- never closed", "<!--<!-- -->-->- Fix"]) {
    assert.ok(!whatsNew(body).includes("<!--"), body);
  }
});
