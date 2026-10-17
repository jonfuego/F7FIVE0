import { useCallback } from "react";
import {
  useCastDevice,
  useCastSession,
  useRemoteMediaClient,
  useStreamPosition,
  type MediaLoadRequest,
} from "react-native-google-cast";

import {
  buildMusicQueueLoadRequest,
  buildVideoLoadRequest,
  type MusicQueueInput,
  type VideoCastInput,
} from "./payloads";

/** Cast controller hook. Exposes connection state plus two hand-off actions
 * that turn a signed video or a music queue into a receiver load. Payloads are
 * built by the pure builders (unit-tested); this hook only owns the native
 * RemoteMediaClient plumbing. No-ops (returns false) when no session is up. */
export function useCast() {
  const client = useRemoteMediaClient();
  const session = useCastSession();
  const isConnected = client !== null && session !== null;

  const castVideo = useCallback(
    async (input: VideoCastInput): Promise<boolean> => {
      if (!client) return false;
      await client.loadMedia(
        buildVideoLoadRequest(input) as unknown as MediaLoadRequest,
      );
      return true;
    },
    [client],
  );

  const castMusicQueue = useCallback(
    async (input: MusicQueueInput): Promise<boolean> => {
      if (!client) return false;
      await client.loadMedia(
        buildMusicQueueLoadRequest(input) as unknown as MediaLoadRequest,
      );
      return true;
    },
    [client],
  );

  const stopCasting = useCallback(async (): Promise<void> => {
    if (client) await client.stop();
  }, [client]);

  return { isConnected, client, session, castVideo, castMusicQueue, stopCasting };
}

/** What the video player needs while a movie plays on the receiver: the device
 * name, the receiver's own place in the stream (seconds, null when it has
 * none, and null again once the session ends), and play / pause / seek on the
 * receiver. Separate from `useCast` so only the player re-renders on the
 * position tick. */
export function useCastReceiver() {
  const client = useRemoteMediaClient();
  const device = useCastDevice();
  const streamPosition = useStreamPosition(2);

  const play = useCallback(async (): Promise<void> => {
    if (client) await client.play();
  }, [client]);
  const pause = useCallback(async (): Promise<void> => {
    if (client) await client.pause();
  }, [client]);
  const seek = useCallback(
    async (streamSec: number): Promise<void> => {
      if (client) await client.seek({ position: streamSec });
    },
    [client],
  );

  return { deviceName: device?.friendlyName ?? null, streamPosition, play, pause, seek };
}
