// Narrow ambient declarations for the Google Cast SDK (CAF v3, sender side).
// Only covers the surface the Player and cast hook actually use. The full
// @types/chromecast-caf-sender package exists in the DefinitelyTyped
// community but drags in a lot we don't need; this file keeps the types
// explicit and self-contained.
//
// The SDK is loaded at runtime via a <script src="https://www.gstatic.com
// /cv/js/sender/v1/cast_sender.js?loadCastFramework=1" /> tag. Before it
// loads, `window.chrome` and `window.cast` are undefined and the custom
// element `<google-cast-launcher>` is not registered. Calls into these
// APIs must be guarded with runtime presence checks.

// React 19 has no global JSX namespace; custom elements extend React's.
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      // Rendered as a web component once the Cast SDK registers it. The
      // element hides itself when Cast isn't available, so rendering it
      // unconditionally is safe.
      "google-cast-launcher": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement>,
        HTMLElement
      > & {
        "cast-icon-color"?: string;
      };
    }
  }
}

declare global {
  interface Window {
    /**
     * Called by the Cast sender script once the framework has initialized.
     * `ok` is true when the framework is ready; false on environments
     * without Cast support (e.g., non-Chromium browsers).
     */
    __onGCastApiAvailable?: (ok: boolean) => void;
    chrome?: typeof chrome;
    cast?: typeof cast;
  }

  // --- chrome.cast (legacy Cast API, still used for enums and MediaInfo) ---
  namespace chrome.cast {
    const AutoJoinPolicy: {
      readonly ORIGIN_SCOPED: "origin_scoped";
      readonly TAB_AND_ORIGIN_SCOPED: "tab_and_origin_scoped";
      readonly PAGE_SCOPED: "page_scoped";
    };

    class Image {
      constructor(url: string);
      url: string;
      width?: number;
      height?: number;
    }

    interface ErrorLike {
      code?: string;
      description?: string;
      details?: unknown;
    }

    namespace media {
      const DEFAULT_MEDIA_RECEIVER_APP_ID: string;

      class MovieMediaMetadata {
        constructor();
        metadataType: number;
        title?: string;
        subtitle?: string;
        studio?: string;
        releaseYear?: number;
        images?: Image[];
      }

      class GenericMediaMetadata {
        constructor();
        metadataType: number;
        title?: string;
        subtitle?: string;
        images?: Image[];
      }

      class MusicTrackMediaMetadata {
        constructor();
        metadataType: number;
        title?: string;
        artist?: string;
        albumName?: string;
        images?: Image[];
      }

      class MediaInfo {
        constructor(contentId: string, contentType: string);
        contentId: string;
        contentType: string;
        contentUrl?: string;
        streamType?: string;
        metadata?:
          | MovieMediaMetadata
          | GenericMediaMetadata
          | MusicTrackMediaMetadata;
        duration?: number | null;
      }

      class LoadRequest {
        constructor(mediaInfo: MediaInfo);
        mediaInfo: MediaInfo;
        currentTime?: number;
        autoplay?: boolean;
      }
    }
  }

  // --- cast.framework (CAF v3, the modern sender framework) ---
  namespace cast.framework {
    const CastContextEventType: {
      readonly CAST_STATE_CHANGED: "caststatechanged";
      readonly SESSION_STATE_CHANGED: "sessionstatechanged";
    };

    const RemotePlayerEventType: {
      readonly ANY_CHANGE: "anyChanged";
      readonly CURRENT_TIME_CHANGED: "currentTimeChanged";
      readonly IS_CONNECTED_CHANGED: "isConnectedChanged";
      readonly IS_PAUSED_CHANGED: "isPausedChanged";
      readonly DURATION_CHANGED: "durationChanged";
    };

    enum CastState {
      NO_DEVICES_AVAILABLE = "NO_DEVICES_AVAILABLE",
      NOT_CONNECTED = "NOT_CONNECTED",
      CONNECTING = "CONNECTING",
      CONNECTED = "CONNECTED",
    }

    enum SessionState {
      NO_SESSION = "NO_SESSION",
      SESSION_STARTING = "SESSION_STARTING",
      SESSION_STARTED = "SESSION_STARTED",
      SESSION_START_FAILED = "SESSION_START_FAILED",
      SESSION_ENDING = "SESSION_ENDING",
      SESSION_ENDED = "SESSION_ENDED",
      SESSION_RESUMED = "SESSION_RESUMED",
    }

    class CastSession {
      getCastDevice(): { friendlyName: string } | null;
      loadMedia(request: chrome.cast.media.LoadRequest): Promise<void>;
      endSession(stopCasting: boolean): void;
    }

    class CastContext {
      static getInstance(): CastContext;
      setOptions(options: {
        receiverApplicationId: string;
        autoJoinPolicy: string;
      }): void;
      getCurrentSession(): CastSession | null;
      getCastState(): CastState;
      getSessionState(): SessionState;
      addEventListener(
        type: string,
        handler: (event: {
          castState?: CastState;
          sessionState?: SessionState;
        }) => void,
      ): void;
      removeEventListener(
        type: string,
        handler: (event: {
          castState?: CastState;
          sessionState?: SessionState;
        }) => void,
      ): void;
      requestSession(): Promise<void>;
    }

    class RemotePlayer {
      isConnected: boolean;
      isPaused: boolean;
      currentTime: number;
      duration: number;
      mediaInfo: chrome.cast.media.MediaInfo | null;
    }

    class RemotePlayerController {
      constructor(player: RemotePlayer);
      addEventListener(
        type: string,
        handler: (event: { field: string; value: unknown }) => void,
      ): void;
      removeEventListener(
        type: string,
        handler: (event: { field: string; value: unknown }) => void,
      ): void;
      playOrPause(): void;
      stop(): void;
      seek(): void;
    }
  }
}

export {};
