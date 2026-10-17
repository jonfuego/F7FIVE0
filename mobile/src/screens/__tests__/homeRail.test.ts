import { readFileSync } from "fs";
import { join } from "path";

// The Home rail holds movies, shows, albums and podcasts in progress, so its
// title must not say "Watching". A source-text check: HomeScreen is a screen
// with no pure helper to call, and the label is the whole behaviour.
const source = readFileSync(join(__dirname, "..", "HomeScreen.tsx"), "utf8");

describe("Home continue rail", () => {
  it("is titled Continue, not Continue Watching", () => {
    expect(source).not.toContain("Continue Watching");
    expect(source).toMatch(/<Text style=\{styles\.rail\}>Continue<\/Text>/);
  });
});
