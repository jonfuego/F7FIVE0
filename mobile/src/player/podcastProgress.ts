/** Saves a podcast episode's place on the server. Pure (no native imports), so it
 * unit tests in Node; PlayerProvider builds it with the real player, API and
 * offline buffer, and the playback service (service.ts) drives it from native
 * events through `podcastSaverBridge`.
 *
 * Why it lives here and not in a React effect: an episode that plays for an
 * hour with the screen off must keep saving. The playback service runs for as
 * long as audio plays, and the native player sends PlaybackProgressUpdated every
 * 15 s and PlaybackState on every pause, so the saves no longer depend on a JS
 * timer or a React render. Each read is native: the active track, its position
 * and whether it is playing.
 *
 * Every save carries the time the position was read (`recordedAtMs`). The server
 * ignores a save older than the one it has, so a late retry or an offline
 * replay never moves the place back. A save that fails goes to the offline
 * buffer; a save that succeeds removes any older buffered save for that episode.
 */

export type PodcastSaveReason = "tick" | "pause" | "switch" | "end";

export interface PodcastSave {
  episodeId: string;
  positionSec: number;
  durationSec?: number;
  recordedAtMs: number;
  /** Which path sent it, for the server log ("phone-tick", "phone-pause", ...). */
  client: string;
}

export interface PodcastSaverDeps {
  /** The episode the app thinks is loaded, or null when no episode is. */
  currentEpisode: () => { episodeId: string; durationSec?: number | null } | null;
  /** Native player: the id of the loaded track (an episode id for podcasts). */
  activeTrackId: () => Promise<string | null>;
  /** Native player position and length in seconds. */
  progress: () => Promise<{ position: number; duration: number }>;
  /** Native player: is it playing right now. */
  isPlaying: () => Promise<boolean>;
  online: () => boolean;
  /** PUT the save; rejects when the server can't be reached. */
  send: (save: PodcastSave) => Promise<void>;
  /** Keep a save for later (offline, or the send failed). */
  buffer: (save: PodcastSave) => void;
  /** Drop buffered saves for this episode taken at or before `atMs`. */
  clearBuffered: (episodeId: string, atMs: number) => void;
  now?: () => number;
}

/** Half the 15 s native interval: a tick right after another save is skipped. */
export const MIN_TICK_GAP_MS = 7_500;

/** For this long after an episode starts, a tick that reads well short of the
 * place it was started at is not saved (the seek may not have landed yet). */
export const START_GUARD_MS = 60_000;

export class PodcastProgressSaver {
  private lastSaveAt = 0;
  private suspended = false;
  private startGuard: { atSec: number; untilMs: number } | null = null;
  private readonly now: () => number;

  constructor(private readonly deps: PodcastSaverDeps) {
    this.now = deps.now ?? Date.now;
  }

  /** While an episode is being loaded and sought, the player reports a stop and
   * a 0 position that are not the listener's place. No saves until `resume()`. */
  suspend(): void {
    this.suspended = true;
  }

  /** Saves allowed again. `startedAtSec` is the place the episode was started
   * at: for a minute, a tick that reads more than 30 s short of it is not saved,
   * so a seek that has not landed cannot replace the saved place with ~0. A
   * pause still saves (the listener may have gone back on purpose). */
  resume(startedAtSec = 0): void {
    this.suspended = false;
    this.startGuard = startedAtSec > 30 ? { atSec: startedAtSec, untilMs: this.now() + START_GUARD_MS } : null;
  }

  /** Save the loaded episode's place. Returns the save made, or null when
   * nothing was saved (no episode, another track loaded, a tick too soon or
   * while paused, suspended). Never throws. */
  async save(reason: PodcastSaveReason): Promise<PodcastSave | null> {
    if (this.suspended) return null;
    try {
      const ep = this.deps.currentEpisode();
      if (!ep) return null;
      if (reason === "tick" && this.now() - this.lastSaveAt < MIN_TICK_GAP_MS) return null;
      // The native player must have this episode loaded, else the position is
      // some other track's (or 0 after a reset).
      // At the end of an episode the player may already have let the track go.
      const active = await this.deps.activeTrackId();
      if (active !== ep.episodeId && !(reason === "end" && active === null)) return null;
      if (reason === "tick" && !(await this.deps.isPlaying())) return null;
      const p = await this.deps.progress();
      const guard = this.startGuard;
      if (guard && this.now() >= guard.untilMs) this.startGuard = null;
      else if (guard && reason === "tick" && p.position < guard.atSec - 30) return null;
      const duration = p.duration > 0 ? p.duration : ep.durationSec ?? 0;
      const position = reason === "end" && duration > 0 ? duration : p.position;
      const save: PodcastSave = {
        episodeId: ep.episodeId,
        positionSec: Math.max(0, Math.floor(position)),
        durationSec: duration >= 1 ? Math.floor(duration) : undefined,
        recordedAtMs: this.now(),
        client: `phone-${reason}`,
      };
      this.lastSaveAt = save.recordedAtMs;
      await this.deliver(save);
      return save;
    } catch {
      return null;
    }
  }

  private async deliver(save: PodcastSave): Promise<void> {
    if (!this.deps.online()) {
      this.deps.buffer(save);
      return;
    }
    try {
      await this.deps.send(save);
      this.deps.clearBuffered(save.episodeId, save.recordedAtMs);
    } catch {
      this.deps.buffer(save);
    }
  }
}

// ---------------------------------------------------------------------------
// Bridge: the playback service has no React context, so PlayerProvider puts its
// saver here and the service's native event handlers call it.
// ---------------------------------------------------------------------------
let current: PodcastProgressSaver | null = null;

export const podcastSaverBridge = {
  set(saver: PodcastProgressSaver | null): void {
    current = saver;
  },
  get(): PodcastProgressSaver | null {
    return current;
  },
  save(reason: PodcastSaveReason): Promise<PodcastSave | null> {
    return current ? current.save(reason) : Promise.resolve(null);
  },
};
