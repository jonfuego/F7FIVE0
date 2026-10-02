// TV stub for the cast hook. react-native-google-cast is a phone/tablet sender
// and is excluded from the TV build, so metro resolves this .tv.ts ahead of
// useCast.ts and the TV bundle never imports the native module. Everything is a
// no-op: there is no cast on the TV.
import type { MusicQueueInput, VideoCastInput } from "./payloads";

export function useCast() {
  return {
    isConnected: false as const,
    client: null,
    session: null,
    castVideo: async (_input: VideoCastInput): Promise<boolean> => false,
    castMusicQueue: async (_input: MusicQueueInput): Promise<boolean> => false,
    stopCasting: async (): Promise<void> => {},
  };
}
