import { downloadToSong, songEntries, songEntry } from "../entries";
import type { SongRow } from "@/api/types";

const song: SongRow = {
  id: "t1",
  title: "Roygbiv",
  duration_sec: 150,
  album_id: "al1",
  album_title: "Music Has the Right",
  cover_path: "/api/art/album/al1/cover",
  artist_id: "ar1",
  artist_name: "Boards of Canada",
  media_files: [{ id: "mf1", container: "flac" }],
};

describe("download entries", () => {
  it("songEntry carries enough metadata to play offline", () => {
    const e = songEntry(song, "Music Has the Right");
    expect(e?.mediaFileId).toBe("mf1");
    expect(e?.opts.kind).toBe("track");
    expect(e?.opts.meta?.container).toBe("flac");
    expect(e?.opts.meta?.group).toBe("Music Has the Right");
  });

  it("songEntries skips rows without a media file", () => {
    expect(songEntries([song, { ...song, id: "t2", media_files: [] }]).map((e) => e.mediaFileId)).toEqual(["mf1"]);
  });

  it("downloadToSong round-trips a finished download into a playable row", () => {
    const e = songEntry(song)!;
    const row = downloadToSong({
      id: e.mediaFileId,
      title: e.title,
      status: "done",
      progress: 1,
      bytes: 10,
      localPath: "file:///x/mf1.flac",
      kind: e.opts.kind,
      meta: e.opts.meta,
    });
    expect(row.id).toBe("t1");
    expect(row.media_files[0].id).toBe("mf1");
    expect(row.artist_name).toBe("Boards of Canada");
  });
});
