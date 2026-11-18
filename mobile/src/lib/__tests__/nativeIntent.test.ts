import { isNotificationClick, redirectSystemPath } from "../nativeIntent";

describe("redirectSystemPath", () => {
  const tap = "trackplayer://notification.click";

  it("keeps a running app where it was on a notification tap", () => {
    expect(redirectSystemPath(tap, false)).toBe("");
  });

  it("opens Home when the tap starts the app", () => {
    expect(redirectSystemPath(tap, true)).toBe("/");
  });

  it("passes every other link through", () => {
    expect(redirectSystemPath("f7five0://watch/abc", false)).toBe("f7five0://watch/abc");
    expect(redirectSystemPath("/podcasts", true)).toBe("/podcasts");
  });

  it("matches the scheme in any case", () => {
    expect(isNotificationClick("TrackPlayer://notification.click")).toBe(true);
    expect(isNotificationClick("https://trackplayer.example/")).toBe(false);
  });
});
