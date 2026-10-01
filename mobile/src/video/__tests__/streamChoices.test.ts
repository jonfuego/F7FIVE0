import {
  audioLabel,
  defaultAudioIndex,
  isTextSubtitle,
  normalizeSubtitle,
  qualityLabel,
  QUALITIES,
  subtitleLabel,
} from "../streamChoices";

describe("qualityLabel", () => {
  it("titles Original and passes through resolutions", () => {
    expect(qualityLabel("original")).toBe("Original");
    expect(qualityLabel("1080p")).toBe("1080p");
    expect(QUALITIES).toEqual(["original", "1080p", "720p", "480p"]);
  });
});

describe("audioLabel", () => {
  it("builds a language/title/codec/channels label", () => {
    expect(audioLabel({ index: 0, codec: "eac3", language: "eng", channels: 6, title: "Surround" })).toBe(
      "ENG · Surround · EAC3 · 5.1",
    );
    expect(audioLabel({ index: 1, codec: "aac", language: "jpn", channels: 2 })).toBe("JPN · AAC · Stereo");
    expect(audioLabel({ index: 2, codec: "" })).toBe("Track 2");
  });
});

describe("subtitleLabel", () => {
  it("builds a language/title/forced label", () => {
    expect(subtitleLabel({ index: 0, codec: "subrip", language: "eng" })).toBe("ENG");
    expect(subtitleLabel({ index: 1, codec: "subrip", language: "eng", forced: true, title: "SDH" })).toBe(
      "ENG · SDH · Forced",
    );
    expect(subtitleLabel({ index: 3, codec: "hdmv_pgs" })).toBe("Subtitle 3");
  });
});

describe("defaultAudioIndex", () => {
  it("prefers the default-flagged stream, then the first, else undefined", () => {
    expect(defaultAudioIndex([{ index: 0, codec: "aac" }, { index: 1, codec: "ac3", default: true }])).toBe(1);
    expect(defaultAudioIndex([{ index: 4, codec: "aac" }, { index: 5, codec: "ac3" }])).toBe(4);
    expect(defaultAudioIndex([])).toBeUndefined();
  });
});

describe("subtitle choice helpers", () => {
  it("identifies text subtitle indices", () => {
    expect(isTextSubtitle(2)).toBe(true);
    expect(isTextSubtitle("off")).toBe(false);
    expect(isTextSubtitle("burn")).toBe(false);
  });

  it("normalizes a null/undefined choice to off", () => {
    expect(normalizeSubtitle(null)).toBe("off");
    expect(normalizeSubtitle(undefined)).toBe("off");
    expect(normalizeSubtitle(3)).toBe(3);
    expect(normalizeSubtitle("burn")).toBe("burn");
  });
});
