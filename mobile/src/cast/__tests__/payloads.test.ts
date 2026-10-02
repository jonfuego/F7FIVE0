import {
  HLS_CONTENT_TYPE,
  MP4_CONTENT_TYPE,
  audioContentType,
  buildMusicQueueLoadRequest,
  buildVideoLoadRequest,
} from "@/cast/payloads";

describe("buildVideoLoadRequest", () => {
  it("builds an HLS video load with the HLS content type and start position", () => {
    const req = buildVideoLoadRequest({
      url: "https://media.example.com/stream/hls/abc/master.m3u8?sig=x",
      mode: "hls",
      title: "The Matrix (1999)",
      artUrl: "https://media.example.com/api/art/movie/abc/poster?sig=y",
      startPositionSec: 273,
      isMovie: true,
    });
    expect(req.mediaInfo?.contentType).toBe(HLS_CONTENT_TYPE);
    expect(req.mediaInfo?.contentType).toBe("application/vnd.apple.mpegurl");
    expect(req.startTime).toBe(273);
    expect(req.autoplay).toBe(true);
    expect(req.mediaInfo?.metadata.title).toBe("The Matrix (1999)");
    expect(req.mediaInfo?.metadata.images?.[0].url).toContain("/api/art/");
  });

  it("builds a direct video load with the mp4 content type", () => {
    const req = buildVideoLoadRequest({
      url: "https://media.example.com/stream/direct/def?sig=x",
      mode: "direct",
      title: "Episode",
    });
    expect(req.mediaInfo?.contentType).toBe(MP4_CONTENT_TYPE);
    expect(req.mediaInfo?.contentType).toBe("video/mp4");
    // No resume position -> no startTime.
    expect(req.startTime).toBeUndefined();
  });
});

describe("buildMusicQueueLoadRequest", () => {
  const tracks = [
    { url: "https://media.example.com/stream/direct/t1?sig=1", title: "One", artist: "A", artUrl: "https://media.example.com/api/art/album/a1/cover?sig=1", container: "flac" },
    { url: "https://media.example.com/stream/direct/t2?sig=2", title: "Two", artist: "A", artUrl: "https://media.example.com/api/art/album/a1/cover?sig=2", container: "mp3" },
    { url: "https://media.example.com/stream/direct/t3?sig=3", title: "Three", artist: "A", artUrl: "https://media.example.com/api/art/album/a1/cover?sig=3", container: "m4a" },
  ];

  it("keeps queue items in order with the start index, start position and art", () => {
    const req = buildMusicQueueLoadRequest({ tracks, startIndex: 1, startPositionSec: 42 });
    expect(req.queueData?.items).toHaveLength(3);
    expect(req.queueData?.items.map((i) => i.mediaInfo.contentUrl)).toEqual([
      tracks[0].url,
      tracks[1].url,
      tracks[2].url,
    ]);
    expect(req.queueData?.startIndex).toBe(1);
    expect(req.queueData?.startTime).toBe(42);
    expect(req.startTime).toBe(42);
    // Every item carries audio/* content and album art.
    for (const item of req.queueData!.items) {
      expect(item.mediaInfo.contentType.startsWith("audio/")).toBe(true);
      expect(item.mediaInfo.metadata.images?.[0].url).toContain("/api/art/");
    }
  });

  it("clamps an out-of-range start index", () => {
    const req = buildMusicQueueLoadRequest({ tracks, startIndex: 99 });
    expect(req.queueData?.startIndex).toBe(2);
  });
});

describe("audioContentType", () => {
  it("maps common containers to audio mime types", () => {
    expect(audioContentType({ container: "flac" })).toBe("audio/flac");
    expect(audioContentType({ container: "mp3" })).toBe("audio/mpeg");
    expect(audioContentType({ container: "m4a" })).toBe("audio/mp4");
    expect(audioContentType({ container: "weird" })).toBe("audio/mpeg");
  });
});
