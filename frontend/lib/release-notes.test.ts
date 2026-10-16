// node:test coverage for the release notes Markdown reader.
//
// Run: node --test frontend/lib/release-notes.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { parseInline, parseReleaseNotes } from "./release-notes.ts";

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
