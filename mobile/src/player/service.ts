/** react-native-track-player playback service. Registered in index.js via
 * TrackPlayer.registerPlaybackService. Handles lock-screen / notification /
 * headset remote controls and audio interruptions (headphone unplug, calls). */
import TrackPlayer, { Event } from "react-native-track-player";

export async function PlaybackService(): Promise<void> {
  TrackPlayer.addEventListener(Event.RemotePlay, () => TrackPlayer.play());
  TrackPlayer.addEventListener(Event.RemotePause, () => TrackPlayer.pause());
  TrackPlayer.addEventListener(Event.RemoteStop, () => TrackPlayer.pause());
  TrackPlayer.addEventListener(Event.RemoteNext, () => TrackPlayer.skipToNext());
  TrackPlayer.addEventListener(Event.RemotePrevious, () => TrackPlayer.skipToPrevious());
  TrackPlayer.addEventListener(Event.RemoteSeek, (e) => TrackPlayer.seekTo(e.position));

  // Interruptions: pause on headphone unplug / audio-becoming-noisy and on a
  // transient duck (phone call), resume when the interruption ends.
  TrackPlayer.addEventListener(Event.RemoteDuck, async (e) => {
    if (e.paused || e.permanent) {
      await TrackPlayer.pause();
    } else {
      await TrackPlayer.play();
    }
  });
}
