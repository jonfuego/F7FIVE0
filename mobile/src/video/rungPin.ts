/** Pins the phone's own HLS playback to one rung. With hardware encoding the
 * master playlist offers three rungs and ExoPlayer's adaptive selection hops
 * between them; every hop starts another encode and stops the one it was
 * reading (the server keeps one encode per viewer and file). The web player
 * pins hls.js the same way. Pure, so it unit tests in Node. */

export interface LoadedVideoTrack {
  index: number;
  height?: number;
  bitrate?: number;
}

export interface PinnedTrack {
  type: "resolution";
  value: number;
}

/** The rung to hold: the tallest the playlist offers (the server already capped
 * the ladder at the viewer's quality ceiling). Null when there is one rung or
 * the player reported no heights, so nothing is forced. */
export function pinnedVideoTrack(tracks: readonly LoadedVideoTrack[] | undefined): PinnedTrack | null {
  if (!tracks || tracks.length < 2) return null;
  let best = 0;
  for (const t of tracks) {
    if (typeof t.height === "number" && t.height > best) best = t.height;
  }
  return best > 0 ? { type: "resolution", value: best } : null;
}
