import { pinnedVideoTrack } from "../rungPin";

describe("pinnedVideoTrack", () => {
  it("holds the tallest rung of a ladder", () => {
    const tracks = [
      { index: 0, height: 480 },
      { index: 1, height: 1080 },
      { index: 2, height: 720 },
    ];
    expect(pinnedVideoTrack(tracks)).toEqual({ type: "resolution", value: 1080 });
  });

  it("forces nothing for a single rung or no report", () => {
    expect(pinnedVideoTrack([{ index: 0, height: 720 }])).toBeNull();
    expect(pinnedVideoTrack([])).toBeNull();
    expect(pinnedVideoTrack(undefined)).toBeNull();
  });

  it("forces nothing when no heights are known", () => {
    expect(pinnedVideoTrack([{ index: 0 }, { index: 1, bitrate: 3000 }])).toBeNull();
  });
});
