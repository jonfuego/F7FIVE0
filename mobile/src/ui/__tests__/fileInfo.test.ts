import { fileInfoRows } from "../fileInfo";

describe("episode File info rows", () => {
  const file = {
    id: "f1",
    path: "C:\\TV\\Test Show (2020)\\Season 02\\Test Show S02E01.mkv",
    container: "mkv",
    size_bytes: 9_437_184,
    video_codec: "hevc",
    audio_codec: "ac3",
    audio_channels: 6,
    width: 1920,
    height: 1080,
    bitrate_kbps: 2900,
  };

  it("gives the seven fields in order from the episode's own file", () => {
    const rows = fileInfoRows(file);
    expect(rows.map((r) => r.label)).toEqual([
      "Codec", "Bitrate", "Container", "Resolution", "Audio", "File size", "File path",
    ]);
    expect(rows.map((r) => r.value)).toEqual([
      "HEVC", "2.9 Mbps", "MKV", "1920×1080", "AC3 5.1", "9.0 MB", file.path,
    ]);
  });

  it("shows a dash for anything the scan didn't record", () => {
    expect(fileInfoRows({ id: "f2" }).every((r) => r.value === "—")).toBe(true);
  });
});
