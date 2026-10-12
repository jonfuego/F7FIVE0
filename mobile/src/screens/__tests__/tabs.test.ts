import * as fs from "fs";
import * as path from "path";

import { PHONE_TABS, TV_TABS, isTabVisible, tabsFor } from "../tabs";

describe("which tabs show where", () => {
  it("the phone has a Podcasts tab between Movies & Shows and Search", () => {
    expect(PHONE_TABS).toEqual(["index", "music", "movies", "podcasts", "search", "account"]);
    expect(isTabVisible("podcasts", false)).toBe(true);
  });

  it("Android TV does not show Podcasts, or Account", () => {
    expect(TV_TABS).toEqual(["index", "music", "movies", "search"]);
    expect(TV_TABS).not.toContain("podcasts");
    expect(isTabVisible("podcasts", true)).toBe(false);
    expect(isTabVisible("account", true)).toBe(false);
    expect(isTabVisible("music", true)).toBe(true);
  });

  it("a tab nobody listed is hidden on TV, so a new route never leaks onto the big screen", () => {
    expect(isTabVisible("something-new", true)).toBe(false);
  });

  it("tabsFor picks the list", () => {
    expect(tabsFor(true)).toBe(TV_TABS);
    expect(tabsFor(false)).toBe(PHONE_TABS);
  });

  it("the TV layout builds its tabs from the TV list and never names the Podcasts tab", () => {
    const tv = fs.readFileSync(path.join(__dirname, "..", "TabsLayout.tv.tsx"), "utf8");
    expect(tv).toContain("TV_TABS");
    expect(tv.toLowerCase()).not.toContain("podcast");
  });
});
