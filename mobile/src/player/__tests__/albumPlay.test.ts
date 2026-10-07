import type { AlbumDetail } from "@/api/types";

import { albumIsPlayable, albumToSongs } from "../albumPlay";

function detail(overrides: Partial<AlbumDetail> = {}): AlbumDetail {
  return {
    id: "al-1",
    artist_id: "ar-1",
    artist_name: "Boards of Canada",
    title: "Geogaddi",
    cover_path: "/art/al-1.jpg",
    tracks: [
      {
        id: "t1",
        title: "Ready Lets Go",
        track_number: 1,
        disc_number: 1,
        duration_sec: 61,
        media_files: [{ id: "mf-1" }],
      },
      {
        id: "t2",
        title: "Music Is Math",
        track_number: 2,
        disc_number: 1,
        duration_sec: 318,
        media_files: [{ id: "mf-2" }],
      },
    ],
    ...overrides,
  };
}

describe("albumToSongs", () => {
  it("maps tracks to song rows in order, carrying album metadata", () => {
    const songs = albumToSongs(detail());
    expect(songs.map((s) => s.id)).toEqual(["t1", "t2"]);
    expect(songs[0]).toMatchObject({
      album_id: "al-1",
      album_title: "Geogaddi",
      artist_id: "ar-1",
      artist_name: "Boards of Canada",
      cover_path: "/art/al-1.jpg",
      media_files: [{ id: "mf-1" }],
    });
  });

  it("defaults a missing artist name to an empty string", () => {
    const songs = albumToSongs(detail({ artist_name: null }));
    expect(songs[0].artist_name).toBe("");
  });
});

describe("albumIsPlayable", () => {
  it("is true when a track has a media file", () => {
    expect(albumIsPlayable(detail())).toBe(true);
  });

  it("is false when no track has a media file", () => {
    const d = detail({
      tracks: [
        { id: "t1", title: "x", track_number: 1, disc_number: 1, duration_sec: 1, media_files: [] },
      ],
    });
    expect(albumIsPlayable(d)).toBe(false);
  });
});
