// node:test coverage for the Discography grouping helper.
//
// The Android app has the same helper (mobile/src/lib/discography.ts) and the
// same cases in mobile/src/lib/__tests__/discography.test.ts. Keep them in step.
//
// Run: node --test frontend/lib/discography.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { discographyYear, groupDiscography } from "./discography.ts";

type A = {
  title: string;
  release_date?: string | null;
  album_type?: string | null;
  secondary_types?: string[] | null;
};

const a = (
  title: string,
  album_type: string | null | undefined,
  release_date: string | null | undefined = null,
  secondary_types: string[] | null | undefined = undefined,
): A => ({ title, album_type, release_date, secondary_types });

const titles = (albums: { title: string }[]) => albums.map((x) => x.title);
const ids = (sections: { id: string }[]) => sections.map((s) => s.id);

// One list, grouped the same way on web and Android.
const MIXED: A[] = [
  a("Single One", "Single", "2010-03-01"),
  a("Studio Two", "Album", "2005-06-01"),
  a("EP One", "EP", "2003-01-01"),
  a("Greatest Hits", "Album", "2008-01-01", ["Compilation"]),
  a("Live In Paris", "Album", "2006-01-01", ["Live"]),
  a("Studio One", "Album", "2001-05-01"),
  a("No Type", null, "2000-01-01"),
];

test("sections come out as Albums, EPs, Singles, Other, in that order", () => {
  const sections = groupDiscography(MIXED);
  assert.deepEqual(ids(sections), ["albums", "eps", "singles", "other"]);
  assert.deepEqual(sections.map((s) => s.title), ["Albums", "EPs", "Singles", "Other"]);
  assert.deepEqual(titles(sections[0].albums), ["Studio One", "Studio Two"]);
  assert.deepEqual(titles(sections[1].albums), ["EP One"]);
  assert.deepEqual(titles(sections[2].albums), ["Single One"]);
  assert.deepEqual(titles(sections[3].albums), ["No Type", "Live In Paris", "Greatest Hits"]);
});

test("input order does not change the grouping", () => {
  const forward = groupDiscography(MIXED).map((s) => [s.id, titles(s.albums)]);
  const backward = groupDiscography([...MIXED].reverse()).map((s) => [s.id, titles(s.albums)]);
  assert.deepEqual(backward, forward);
});

test("a compilation goes to Other even when its primary type is Album", () => {
  const sections = groupDiscography([a("Greatest Hits", "Album", "2008-01-01", ["Compilation"])]);
  assert.deepEqual(ids(sections), ["other"]);
});

test("a live album goes to Other even when its primary type is Album", () => {
  const sections = groupDiscography([a("Live In Paris", "Album", "2006-01-01", ["Live"])]);
  assert.deepEqual(ids(sections), ["other"]);
});

test("an EP or a Single that is Live or a Compilation goes to Other", () => {
  const sections = groupDiscography([
    a("Live EP", "EP", "2004-01-01", ["Live"]),
    a("Comp Single", "Single", "2004-01-01", ["Compilation"]),
    a("Plain EP", "EP", "2004-01-01"),
  ]);
  assert.deepEqual(ids(sections), ["eps", "other"]);
  assert.deepEqual(titles(sections[0].albums), ["Plain EP"]);
  assert.deepEqual(titles(sections[1].albums), ["Comp Single", "Live EP"]);
});

test("Live next to other secondary types still goes to Other", () => {
  const sections = groupDiscography([a("Mixed Bag", "Album", "2004-01-01", ["Remix", "Live"])]);
  assert.deepEqual(ids(sections), ["other"]);
});

test("Soundtrack, Remix, DJ-mix, Mixtape/Street, Demo, Spokenword, Interview, Audiobook and Audio drama go to Other", () => {
  const kinds = [
    "Soundtrack", "Remix", "DJ-mix", "Mixtape/Street", "Demo",
    "Spokenword", "Interview", "Audiobook", "Audio drama",
  ];
  for (const kind of kinds) {
    const sections = groupDiscography([a(`As ${kind}`, "Album", "2004-01-01", [kind])]);
    assert.deepEqual(ids(sections), ["other"]);
  }
});

test("a secondary type the list does not know is ignored", () => {
  const sections = groupDiscography([a("Odd", "Album", "2004-01-01", ["Something New"])]);
  assert.deepEqual(ids(sections), ["albums"]);
});

test("an album with no type goes to Other (null, undefined, empty, blank)", () => {
  const sections = groupDiscography([
    a("Null Type", null, "2001-01-01"),
    a("Undefined Type", undefined, "2002-01-01"),
    a("Empty Type", "", "2003-01-01"),
    a("Blank Type", "   ", "2004-01-01"),
  ]);
  assert.deepEqual(ids(sections), ["other"]);
  assert.deepEqual(titles(sections[0].albums), ["Null Type", "Undefined Type", "Empty Type", "Blank Type"]);
});

test("an unknown primary type, Broadcast or Other goes to Other", () => {
  const sections = groupDiscography([
    a("On Air", "Broadcast", "2001-01-01"),
    a("Misc", "Other", "2002-01-01"),
    a("Weird", "Mixtape", "2003-01-01"),
  ]);
  assert.deepEqual(ids(sections), ["other"]);
  assert.deepEqual(sections[0].albums.length, 3);
});

test("empty sections are hidden", () => {
  assert.deepEqual(ids(groupDiscography([a("Only Album", "Album", "2001-01-01")])), ["albums"]);
  assert.deepEqual(ids(groupDiscography([a("Only EP", "EP", "2001-01-01")])), ["eps"]);
  assert.deepEqual(ids(groupDiscography([a("Only Single", "Single", "2001-01-01")])), ["singles"]);
  assert.deepEqual(
    ids(groupDiscography([a("An Album", "Album"), a("A Single", "Single")])),
    ["albums", "singles"],
  );
  assert.deepEqual(groupDiscography([]), []);
});

test("albums inside a section are ordered by year, oldest first", () => {
  const sections = groupDiscography([
    a("Third", "Album", "2015-01-01"),
    a("First", "Album", "1994-09-09"),
    a("Second", "Album", "2003-03-03"),
  ]);
  assert.deepEqual(titles(sections[0].albums), ["First", "Second", "Third"]);
});

test("the year decides first, and albums in the same year sort by title", () => {
  const sections = groupDiscography([
    a("Zed", "Album", "2001-01-01"),
    a("Beta", "Album", "2001-12-31"),
    a("alpha", "Album", "2001-06-30"),
    a("Early", "Album", "2000-12-31"),
  ]);
  assert.deepEqual(titles(sections[0].albums), ["Early", "alpha", "Beta", "Zed"]);
});

test("albums with the same year and title keep their input order", () => {
  const first = { ...a("Same", "Album", "2001-01-01"), id: "first" };
  const second = { ...a("Same", "Album", "2001-02-02"), id: "second" };
  const sections = groupDiscography([first, second]);
  assert.deepEqual(sections[0].albums.map((x) => x.id), ["first", "second"]);
});

test("albums with no year sort last, in title order", () => {
  const sections = groupDiscography([
    a("Undated B", "Album", null),
    a("Dated", "Album", "1999-01-01"),
    a("Undated A", "Album", undefined),
    a("Bad Date", "Album", "soon"),
  ]);
  assert.deepEqual(titles(sections[0].albums), ["Dated", "Bad Date", "Undated A", "Undated B"]);
});

test("type matching ignores case and surrounding spaces", () => {
  const sections = groupDiscography([
    a("Lower", "album", "2001-01-01"),
    a("Upper", "ALBUM", "2002-01-01"),
    a("Padded", "  Album  ", "2003-01-01"),
    a("Small EP", "ep", "2004-01-01"),
    a("Mixed EP", " Ep ", "2005-01-01"),
    a("Loud Single", "SINGLE", "2006-01-01"),
    a("Live Lower", "album", "2007-01-01", [" live "]),
    a("Comp Upper", "album", "2008-01-01", ["COMPILATION"]),
  ]);
  assert.deepEqual(ids(sections), ["albums", "eps", "singles", "other"]);
  assert.deepEqual(titles(sections[0].albums), ["Lower", "Upper", "Padded"]);
  assert.deepEqual(titles(sections[1].albums), ["Small EP", "Mixed EP"]);
  assert.deepEqual(titles(sections[2].albums), ["Loud Single"]);
  assert.deepEqual(titles(sections[3].albums), ["Live Lower", "Comp Upper"]);
});

test("missing or null secondary_types are fine", () => {
  const sections = groupDiscography([
    a("Undef", "Album", "2001-01-01", undefined),
    a("Null", "Album", "2002-01-01", null),
    a("Empty", "Album", "2003-01-01", []),
  ]);
  assert.deepEqual(ids(sections), ["albums"]);
  assert.deepEqual(sections[0].albums.length, 3);
});

test("the input array is not changed and the album objects come back as they went in", () => {
  const input = [a("B", "Album", "2002-01-01"), a("A", "Album", "2001-01-01")];
  const copy = [...input];
  const sections = groupDiscography(input);
  assert.deepEqual(input, copy);
  assert.deepEqual(sections[0].albums[0], input[1]);
});

test("discographyYear reads the leading four digits", () => {
  assert.deepEqual(discographyYear("2001-05-01"), 2001);
  assert.deepEqual(discographyYear("1999"), 1999);
  assert.deepEqual(discographyYear("2001-05-01T00:00:00Z"), 2001);
  assert.deepEqual(discographyYear(null), null);
  assert.deepEqual(discographyYear(undefined), null);
  assert.deepEqual(discographyYear(""), null);
  assert.deepEqual(discographyYear("0000-00-00"), null);
  assert.deepEqual(discographyYear("n/a"), null);
});
