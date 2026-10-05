// Player controller interface (web). Item 8c groundwork for watch-together.
//
// One uniform way to drive any player (the /watch <video>, the audio dock's
// MiniPlayer) so a future room / remote can command playback without knowing
// which concrete player is mounted. This is a REFACTOR: it describes the
// controls the existing players already have (play, pause, seek, set rate) plus
// the signals they already emit (position, buffering, ended). Behavior is
// unchanged; the existing components adopt the interface so there is one shape
// to target later.
//
// Positions are SOURCE seconds (absolute in the media), not element-clock
// seconds, so a resumed HLS stream and a direct-play file speak the same units.

export type PlayerEventMap = {
  // Source-second playhead updates (fired as playback advances / on seek).
  position: number;
  // True while the player is waiting on data, false once it can play.
  buffering: boolean;
  // Playback reached the end of the media.
  ended: void;
};

export type PlayerEvent = keyof PlayerEventMap;

export interface PlayerController {
  play(): void;
  pause(): void;
  /** Seek to an absolute SOURCE second. */
  seek(sourceSec: number): void;
  /** Set the playback rate (1 = normal). */
  setRate(rate: number): void;

  /** Current absolute source second. */
  getPosition(): number;
  /** True if currently paused. */
  isPaused(): boolean;

  /** Subscribe to a player event. Returns an unsubscribe function. */
  on<E extends PlayerEvent>(
    event: E,
    handler: (payload: PlayerEventMap[E]) => void,
  ): () => void;
}

// A tiny typed emitter the concrete controllers share, so each player does not
// re-implement listener bookkeeping.
export class PlayerEmitter {
  private readonly listeners: {
    [E in PlayerEvent]: Set<(payload: PlayerEventMap[E]) => void>;
  } = {
    position: new Set(),
    buffering: new Set(),
    ended: new Set(),
  };

  on<E extends PlayerEvent>(
    event: E,
    handler: (payload: PlayerEventMap[E]) => void,
  ): () => void {
    this.listeners[event].add(handler);
    return () => {
      this.listeners[event].delete(handler);
    };
  }

  emit<E extends PlayerEvent>(event: E, payload: PlayerEventMap[E]): void {
    for (const h of this.listeners[event]) h(payload);
  }
}

/** Build a PlayerController backed by an HTMLMediaElement (<video> or <audio>).
 *
 * `offsetSec` is where the element clock 0 sits in the source (the bucketed HLS
 * encode start; 0 for direct play and for audio), so positions and seeks are
 * translated to SOURCE seconds. Used by the /watch video path (VideoTransport)
 * and the audio dock (MiniPlayer). */
export function videoElementController(
  getVideoEl: () => HTMLMediaElement | null,
  offsetSec: () => number,
): PlayerController & { dispose: () => void } {
  const emitter = new PlayerEmitter();
  let bound: HTMLMediaElement | null = null;

  const onTime = () => {
    const v = bound;
    if (v) emitter.emit("position", offsetSec() + (v.currentTime || 0));
  };
  const onWaiting = () => emitter.emit("buffering", true);
  const onPlaying = () => emitter.emit("buffering", false);
  const onEnded = () => emitter.emit("ended", undefined);

  function ensureBound() {
    const v = getVideoEl();
    if (v === bound) return;
    if (bound) {
      bound.removeEventListener("timeupdate", onTime);
      bound.removeEventListener("waiting", onWaiting);
      bound.removeEventListener("playing", onPlaying);
      bound.removeEventListener("ended", onEnded);
    }
    bound = v;
    if (bound) {
      bound.addEventListener("timeupdate", onTime);
      bound.addEventListener("waiting", onWaiting);
      bound.addEventListener("playing", onPlaying);
      bound.addEventListener("ended", onEnded);
    }
  }

  return {
    play() {
      ensureBound();
      const p = bound?.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    },
    pause() {
      ensureBound();
      bound?.pause();
    },
    seek(sourceSec: number) {
      ensureBound();
      if (!bound) return;
      try {
        bound.currentTime = Math.max(0, sourceSec - offsetSec());
      } catch {
        // ignore
      }
    },
    setRate(rate: number) {
      ensureBound();
      if (bound) bound.playbackRate = rate;
    },
    getPosition() {
      ensureBound();
      return bound ? offsetSec() + (bound.currentTime || 0) : 0;
    },
    isPaused() {
      ensureBound();
      return bound ? bound.paused : true;
    },
    on: (event, handler) => {
      ensureBound();
      return emitter.on(event, handler);
    },
    dispose() {
      if (bound) {
        bound.removeEventListener("timeupdate", onTime);
        bound.removeEventListener("waiting", onWaiting);
        bound.removeEventListener("playing", onPlaying);
        bound.removeEventListener("ended", onEnded);
      }
      bound = null;
    },
  };
}
