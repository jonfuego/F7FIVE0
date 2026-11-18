import type { ContinueWatchingItem } from "@/api/types";
import { continueArtFit, continueTarget } from "../continueTarget";

const base: ContinueWatchingItem = {
  kind: "movie",
  id: "m1",
  media_file_id: "f1",
  title: "Dances with Wolves",
  position_sec: 600,
  duration_sec: 10800,
};

describe("continueTarget", () => {
  it("opens the player for a movie, show, album or music video", () => {
    expect(continueTarget(base)).toEqual({ type: "watch", href: "/watch/f1" });
  });

  it("plays a podcast episode by its id, resuming from the server", () => {
    const ep: ContinueWatchingItem = {
      kind: "podcast_episode",
      id: "e1",
      podcast_id: "p1",
      media_file_id: null,
      title: "Supernova in the East",
      subtitle: "Hardcore History",
      poster_path: "/api/art/podcast/p1/cover",
      position_sec: 900,
      duration_sec: 3600,
    };
    expect(continueTarget(ep)).toEqual({
      type: "episode",
      episode: {
        id: "e1",
        podcastId: "p1",
        title: "Supernova in the East",
        showTitle: "Hardcore History",
        coverPath: "/api/art/podcast/p1/cover",
        durationSec: 3600,
      },
    });
  });

  it("does nothing for a non-podcast row with no file", () => {
    expect(continueTarget({ ...base, media_file_id: null })).toEqual({ type: "none" });
  });

  it("shows square podcast covers whole", () => {
    expect(continueArtFit({ ...base, kind: "podcast_episode" })).toBe("contain");
    expect(continueArtFit(base)).toBe("cover");
  });
});
