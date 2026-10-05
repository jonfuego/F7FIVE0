/** Player controller interface (app). Item 8c groundwork for watch-together.
 *
 * One uniform way to drive either app player (the react-native-video
 * VideoPlayer, the react-native-track-player audio service) so a future room /
 * remote can command playback without knowing which player is active. This is a
 * REFACTOR: it describes the controls the players already have (play, pause,
 * seek, set rate) plus the signals they already emit (position, buffering,
 * ended). Behavior is unchanged; the existing players adopt the interface.
 *
 * Positions are SOURCE seconds (absolute in the media), matching the web
 * controller, so a resumed HLS stream and a direct-play file speak one unit.
 */

export type PlayerEventMap = {
  /** Source-second playhead updates. */
  position: number;
  /** True while waiting on data, false once playing. */
  buffering: boolean;
  /** Playback reached the end. */
  ended: void;
};

export type PlayerEvent = keyof PlayerEventMap;

export interface PlayerController {
  play(): void | Promise<void>;
  pause(): void | Promise<void>;
  /** Seek to an absolute SOURCE second. */
  seek(sourceSec: number): void | Promise<void>;
  /** Set the playback rate (1 = normal). */
  setRate(rate: number): void | Promise<void>;

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

/** Shared typed emitter so each controller does not re-implement listener
 * bookkeeping. */
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

/** The subset of react-native-video's ref the controller drives. Declared here
 * (not imported) so this module stays free of native imports and unit-tests in
 * Node. VideoPlayer passes its ref.current. */
export interface VideoRefLike {
  seek(seconds: number): void;
}

/** Build a controller for the react-native-video player.
 *
 * `baseSec` is where the element clock 0 sits in the source (the HLS bucket; 0
 * for direct play), so seeks and positions are source-absolute. The owning
 * component feeds progress/buffering/ended into the returned emitter from the
 * <Video> callbacks it already handles. */
export function videoController(deps: {
  getRef: () => VideoRefLike | null;
  getBase: () => number;
  getPosition: () => number;
  getPaused: () => boolean;
  setPaused: (paused: boolean) => void;
  setRate: (rate: number) => void;
}): PlayerController & { emitter: PlayerEmitter } {
  const emitter = new PlayerEmitter();
  return {
    emitter,
    play() {
      deps.setPaused(false);
    },
    pause() {
      deps.setPaused(true);
    },
    seek(sourceSec: number) {
      const ref = deps.getRef();
      if (ref) ref.seek(Math.max(0, sourceSec - deps.getBase()));
    },
    setRate(rate: number) {
      deps.setRate(rate);
    },
    getPosition: deps.getPosition,
    isPaused: deps.getPaused,
    on: (event, handler) => emitter.on(event, handler),
  };
}

/** The subset of react-native-track-player the audio controller drives.
 * Declared here (not imported) so this module has no native import; the owner
 * passes TrackPlayer. All methods are async in the real library. */
export interface TrackPlayerLike {
  play(): Promise<void>;
  pause(): Promise<void>;
  seekTo(seconds: number): Promise<void>;
  setRate(rate: number): Promise<void>;
}

/** Build a controller for the react-native-track-player audio service. Audio is
 * direct-play, so positions are already source-absolute (no base). The owner
 * feeds progress / state into the emitter from the TrackPlayer events it
 * already subscribes to. */
export function trackPlayerController(deps: {
  trackPlayer: TrackPlayerLike;
  getPosition: () => number;
  getPaused: () => boolean;
}): PlayerController & { emitter: PlayerEmitter } {
  const emitter = new PlayerEmitter();
  return {
    emitter,
    play: () => deps.trackPlayer.play(),
    pause: () => deps.trackPlayer.pause(),
    seek: (sourceSec: number) => deps.trackPlayer.seekTo(Math.max(0, sourceSec)),
    setRate: (rate: number) => deps.trackPlayer.setRate(rate),
    getPosition: deps.getPosition,
    isPaused: deps.getPaused,
    on: (event, handler) => emitter.on(event, handler),
  };
}
