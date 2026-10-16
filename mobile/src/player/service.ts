/** react-native-track-player playback service. Registered in index.js via
 * TrackPlayer.registerPlaybackService. Handles lock-screen / notification /
 * headset remote controls and audio interruptions (headphone unplug, calls). */
import TrackPlayer, { Event, State } from "react-native-track-player";
import { skipBack, skipForward } from "./longform";
import { podcastSaverBridge } from "./podcastProgress";
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

  // Podcast mode (see setup.ts): the notification and headset jump back 15 s and
  // forward 30 s. The jump stays inside the episode.
  TrackPlayer.addEventListener(Event.RemoteJumpBackward, async () => {
    const p = await TrackPlayer.getProgress();
    await TrackPlayer.seekTo(skipBack(p.position));
  });
  TrackPlayer.addEventListener(Event.RemoteJumpForward, async () => {
    const p = await TrackPlayer.getProgress();
    await TrackPlayer.seekTo(skipForward(p.position, p.duration));
  });

  // Podcast place: the native player sends PlaybackProgressUpdated every 15 s
  // in podcast mode (setup.ts) and PlaybackState on every change, from this
  // service, so the saves do not depend on a JS timer or a React render. The
  // saver (podcastProgress.ts) does nothing unless an episode is loaded.
  TrackPlayer.addEventListener(Event.PlaybackProgressUpdated, () => {
    void podcastSaverBridge.save("tick");
  });
  TrackPlayer.addEventListener(Event.PlaybackState, (e) => {
    if (e.state === State.Paused || e.state === State.Stopped) void podcastSaverBridge.save("pause");
    else if (e.state === State.Ended) void podcastSaverBridge.save("end");
  });

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
