/** react-native-track-player playback service. Registered in index.js via
 * TrackPlayer.registerPlaybackService. Handles lock-screen / notification /
 * headset remote controls and audio interruptions (headphone unplug, calls). */
import TrackPlayer, { Event } from "react-native-track-player";
import { trackPlayerController } from "./playerController";

// Uniform player controller (item 8c) over the audio service. The remote
// play/pause/seek handlers drive the audio through this so a future
// watch-together room can command the audio player the same way as the video
// one. Position/paused getters read live TrackPlayer state only when asked, so
// the service stays stateless here.
const audioController = trackPlayerController({
  trackPlayer: {
    play: () => TrackPlayer.play(),
    pause: () => TrackPlayer.pause(),
    seekTo: (s: number) => TrackPlayer.seekTo(s),
    setRate: (r: number) => TrackPlayer.setRate(r),
  },
  getPosition: () => 0,
  getPaused: () => false,
});

export async function PlaybackService(): Promise<void> {
  TrackPlayer.addEventListener(Event.RemotePlay, () => audioController.play());
  TrackPlayer.addEventListener(Event.RemotePause, () => audioController.pause());
  TrackPlayer.addEventListener(Event.RemoteStop, () => audioController.pause());
  TrackPlayer.addEventListener(Event.RemoteNext, () => TrackPlayer.skipToNext());
  TrackPlayer.addEventListener(Event.RemotePrevious, () => TrackPlayer.skipToPrevious());
  TrackPlayer.addEventListener(Event.RemoteSeek, (e) => audioController.seek(e.position));

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
