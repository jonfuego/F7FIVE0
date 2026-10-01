// App entry. Registers the track-player playback service BEFORE the router
// boots so background audio (lock-screen / notification controls) works, then
// hands off to Expo Router. The two imports are hoisted and run first; the
// require() for the router runs in place, after registration.
import TrackPlayer from "react-native-track-player";
import { PlaybackService } from "./src/player/service";

TrackPlayer.registerPlaybackService(() => PlaybackService);

require("expo-router/entry");
