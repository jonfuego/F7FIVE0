import TrackPlayer, {
  AndroidAudioContentType,
  AppKilledPlaybackBehavior,
  Capability,
  IOSCategory,
  IOSCategoryMode,
} from "react-native-track-player";

let isSetup = false;

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

  await TrackPlayer.updateOptions({
    android: {
      appKilledPlaybackBehavior: AppKilledPlaybackBehavior.StopPlaybackAndRemoveNotification,
      alwaysPauseOnInterruption: true,
    },
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
  });
  isSetup = true;
}
