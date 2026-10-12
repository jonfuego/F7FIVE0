import { downloadSource, downloadToEpisode, episodeEntry, podcastDownloadPath } from "../podcastEntries";
import type { PodcastEpisodeRow, PodcastShowRef } from "@/api/types";

const show: PodcastShowRef = { id: "p1", title: "The Fixture Show", art_url: "/api/art/podcast/p1/cover?v=1" };
const ep: PodcastEpisodeRow = {
  id: "e1",
  podcast_id: "p1",
  title: "Episode Three",
  description: "Hello",
  published_at: "2025-03-01T08:00:00Z",
  duration_sec: 3723,
  has_file: false,
  container: "mp3",
  state: { kind: "new" },
};

describe("podcast download entries", () => {
  it("an episode entry carries enough to play offline", () => {
    const e = episodeEntry(ep, show);
    expect(e.mediaFileId).toBe("e1");
    expect(e.title).toBe("Episode Three");
    expect(e.opts.kind).toBe("podcast");
    expect(e.opts.meta?.episodeId).toBe("e1");
    expect(e.opts.meta?.podcastId).toBe("p1");
    expect(e.opts.meta?.album).toBe("The Fixture Show");
    expect(e.opts.meta?.group).toBe("The Fixture Show");
    expect(e.opts.meta?.durationSec).toBe(3723);
    expect(e.opts.meta?.container).toBe("mp3");
    expect(e.opts.meta?.coverPath).toBe("/api/art/podcast/p1/cover?v=1");
  });

  it("sources a podcast download from the signed /stream/podcast URL, others from the media file", () => {
    expect(downloadSource("podcast")).toBe("podcast");
    expect(downloadSource("track")).toBe("media");
    expect(downloadSource("movie")).toBe("media");
    expect(downloadSource(undefined)).toBe("media");
    expect(podcastDownloadPath("e1")).toBe("/api/podcasts/episodes/e1/stream");
  });

  it("a finished download turns back into a playable episode with no catalogue lookup", () => {
    const e = episodeEntry(ep, show);
    const local = downloadToEpisode({
      id: e.mediaFileId,
      title: e.title,
      status: "done",
      progress: 1,
      bytes: 10,
      localPath: "file:///x/e1.mp3",
      kind: e.opts.kind,
      meta: e.opts.meta,
    });
    expect(local.id).toBe("e1");
    expect(local.title).toBe("Episode Three");
    expect(local.showTitle).toBe("The Fixture Show");
    expect(local.localPath).toBe("file:///x/e1.mp3");
    expect(local.durationSec).toBe(3723);
    expect(local.coverPath).toBe("/api/art/podcast/p1/cover?v=1");
  });

  it("rejects an episode with no id", () => {
    expect(() => episodeEntry({ ...ep, id: "" }, show)).toThrow();
  });
});
