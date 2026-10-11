import type { SongRow } from "@/api/types";

import { artistRadioId, artistRadioNotice, startArtistRadio } from "../artistRadio";

const song = { id: "s1", title: "One" } as unknown as SongRow;

describe("artistRadioId", () => {
  it("returns the album's artist id", () => {
    expect(artistRadioId({ artist_id: "ar-1" })).toBe("ar-1");
  });

  it("returns null when the artist id is missing or blank", () => {
    expect(artistRadioId({ artist_id: "" })).toBeNull();
    expect(artistRadioId({ artist_id: "   " })).toBeNull();
    expect(artistRadioId({} as { artist_id: string })).toBeNull();
  });
});

describe("startArtistRadio", () => {
  it("plays the songs and reports started", async () => {
    const play = jest.fn();
    const out = await startArtistRadio(async () => [song], play);
    expect(out).toBe("started");
    expect(play).toHaveBeenCalledWith([song]);
  });

  it("does not play an empty radio", async () => {
    const play = jest.fn();
    const out = await startArtistRadio(async () => [], play);
    expect(out).toBe("empty");
    expect(play).not.toHaveBeenCalled();
  });

  it("reports a failed load without throwing or playing", async () => {
    const play = jest.fn();
    const out = await startArtistRadio(() => Promise.reject(new Error("503")), play);
    expect(out).toBe("failed");
    expect(play).not.toHaveBeenCalled();
  });
});

describe("artistRadioNotice", () => {
  it("is silent when playback started and speaks for the other outcomes", () => {
    expect(artistRadioNotice("started")).toBeNull();
    expect(artistRadioNotice("empty")).toMatch(/No artist radio/);
    expect(artistRadioNotice("failed")).toMatch(/Could not start/);
  });
});
