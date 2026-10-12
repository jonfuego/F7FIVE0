import TrackPlayer, {
  AndroidAudioContentType,
  AppKilledPlaybackBehavior,
  Capability,
  IOSCategory,
  IOSCategoryMode,
} from "react-native-track-player";

import { SKIP_BACK_SEC, SKIP_FORWARD_SEC } from "./longform";

export type PlayerMode = "music" | "podcast";

let isSetup = false;
let mode: PlayerMode = "music";

const ANDROID = {
  appKilledPlaybackBehavior: AppKilledPlaybackBehavior.StopPlaybackAndRemoveNotification,
  alwaysPauseOnInterruption: true,
} as const;

/** Lock-screen / notification transport for each mode. Music has Previous and
 * Next. A podcast episode has no previous or next: it gets jump back 15 s and
 * jump forward 30 s instead (the intervals below are what the notification
 * buttons and the headset use). */
function optionsFor(m: PlayerMode) {
  if (m === "podcast") {
    return {
      android: ANDROID,
      forwardJumpInterval: SKIP_FORWARD_SEC,
      backwardJumpInterval: SKIP_BACK_SEC,
      capabilities: [
        Capability.Play,
        Capability.Pause,
        Capability.JumpBackward,
        Capability.JumpForward,
        Capability.SeekTo,
      ],
      compactCapabilities: [Capability.JumpBackward, Capability.Play, Capability.JumpForward],
      notificationCapabilities: [
        Capability.Play,
        Capability.Pause,
        Capability.JumpBackward,
        Capability.JumpForward,
        Capability.SeekTo,
      ],
    };
  }
  return {
    android: ANDROID,
    capabilities: [
      Capability.Play,
      Capability.Pause,
      Capability.SkipToNext,
      Capability.SkipToPrevious,
      Capability.SeekTo,
    ],
    compactCapabilities: [
      Capability.Play,
      Capability.Pause,
      Capability.SkipToNext,
      Capability.SkipToPrevious,
    ],
    notificationCapabilities: [
      Capability.Play,
      Capability.Pause,
      Capability.SkipToNext,
      Capability.SkipToPrevious,
      Capability.SeekTo,
    ],
  };
}

/** Idempotent player setup. Enables background audio, headphone-unplug pause,
 * and the lock-screen / notification transport (Play, Pause, SkipToNext,
 * SkipToPrevious, SeekTo). */
export async function setupPlayer(): Promise<void> {
  if (isSetup) return;
  try {
    await TrackPlayer.setupPlayer({
      autoHandleInterruptions: true,
      iosCategory: IOSCategory.Playback,
      iosCategoryMode: IOSCategoryMode.Default,
      androidAudioContentType: AndroidAudioContentType.Music,
    });
  } catch (e) {
    // "player already initialized" is fine on a fast remount.
    const msg = e instanceof Error ? e.message : String(e);
    if (!/already been initialized|already initialized/i.test(msg)) throw e;
  }

  await TrackPlayer.updateOptions(optionsFor("music"));
  mode = "music";
  isSetup = true;
}

/** Switch the notification and headset transport between music and podcast
 * mode. A no-op when already in that mode. */
export async function setPlayerMode(next: PlayerMode): Promise<void> {
  await setupPlayer();
  if (mode === next) return;
  await TrackPlayer.updateOptions(optionsFor(next));
  mode = next;
}
