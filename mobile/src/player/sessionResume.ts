/** Rebuild the last session when a Play finds the native player empty.
 *
 * The playback service (service.ts) and the car bridge (AndroidAutoBridge.tsx)
 * get a Play with no React context. PlayerProvider registers a resumer here;
 * a Play then asks it to rebuild the last session (lastSession.ts) when the
 * native queue is empty, instead of calling play() on nothing.
 *
 * Pure (no native imports), so it unit tests in Node. */
import type { LastSession } from "./lastSession";

/** ExoPlayer's media session turns a Play on an ended track into a seek to its
 * "unset" time (Long.MIN_VALUE + 1 ms, about -9.2e15 s here). Only a real,
 * finite, non-negative position is a seek. */
export function isUsableSeek(position: unknown): position is number {
  return typeof position === "number" && Number.isFinite(position) && position >= 0 && position < 1e7;
}

export interface ResumeDeps {
  /** How many tracks the native player holds. */
  queueLength: () => Promise<number>;
  /** The session to rebuild (the phone's record, or the server queue). */
  loadSession: () => Promise<LastSession | null>;
  /** Load it and play (or only load it, paused). True when something loaded. */
  restore: (session: LastSession, opts: { play: boolean }) => Promise<boolean>;
  /** Start playback of what is loaded. */
  play: () => Promise<void>;
}

/** Rebuilds once at a time: a Play from the car and one from the headset that
 * arrive together share one rebuild. */
export class SessionResumer {
  private inFlight: Promise<boolean> | null = null;
  private inFlightPlays = false;

  constructor(private readonly deps: ResumeDeps) {}

  /** When the native player is empty, rebuild the last session. Returns true
   * when this handled the request (it rebuilt, or a rebuild is already under
   * way), false when the player has something loaded (the caller plays it) or
   * there is nothing to rebuild. Never throws. */
  resumeIfEmpty(opts: { play: boolean } = { play: true }): Promise<boolean> {
    if (this.inFlight) {
      // A Play during a paused rebuild (the cold start one) plays once loaded.
      if (!opts.play || this.inFlightPlays) return this.inFlight;
      return this.inFlight.then(async (loaded) => {
        if (loaded) await this.deps.play().catch(() => undefined);
        return loaded;
      });
    }
    this.inFlightPlays = opts.play;
    const run = (async () => {
      try {
        if ((await this.deps.queueLength()) > 0) return false;
        const session = await this.deps.loadSession();
        if (!session) return false;
        return await this.deps.restore(session, opts);
      } catch {
        return false;
      }
    })();
    this.inFlight = run;
    void run.finally(() => {
      if (this.inFlight === run) this.inFlight = null;
    });
    return run;
  }
}

let current: SessionResumer | null = null;

export const sessionResumeBridge = {
  set(r: SessionResumer | null): void {
    current = r;
  },
  get(): SessionResumer | null {
    return current;
  },
  resumeIfEmpty(opts?: { play: boolean }): Promise<boolean> {
    return current ? current.resumeIfEmpty(opts) : Promise.resolve(false);
  },
};
