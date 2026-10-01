"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// React hook wrapping the Cast SDK for F7FIVE0. Consolidates three concerns:
//
//   1. Availability + connection state — so the UI can show/hide controls
//      and label the current receiver.
//   2. RemotePlayer mirror — currentTime / duration / isPaused, updated via
//      RemotePlayerController events. These are authoritative while a cast
//      session is active, and the Player component reads them in place of
//      the local <video> element for heartbeat and the scrubber.
//   3. Commands — loadMedia, playPause, seek, stop, endSession. All no-ops
//      before the SDK loads so callers don't need to guard.
//
// The hook must only run in the browser. Callers are client components. A
// top-level guard keeps SSR happy if anyone imports this from a server file
// by accident.

type CastFramework = typeof cast.framework;
type ChromeCast = typeof chrome.cast;

export type CastStatus =
  | "unavailable" // SDK failed to load or browser doesn't support Cast
  | "no_devices" // SDK loaded, no receivers on the network
  | "available" // receivers visible, not connected
  | "connecting"
  | "connected";

export interface CastMediaPayload {
  contentUrl: string; // absolute URL the receiver can fetch
  contentType: string; // e.g. "application/vnd.apple.mpegurl" or "video/mp4"
  title?: string;
  subtitle?: string;
  posterUrl?: string; // absolute URL for receiver artwork
  startTime?: number; // seconds
  durationSec?: number | null;
}

export interface UseCastResult {
  status: CastStatus;
  deviceName: string | null;
  isConnected: boolean;
  isPaused: boolean;
  currentTime: number; // seconds, mirrored from RemotePlayer
  duration: number; // seconds, mirrored from RemotePlayer
  loadMedia: (payload: CastMediaPayload) => Promise<void>;
  playPause: () => void;
  seek: (seconds: number) => void;
  stop: () => void;
  endSession: (stopCasting?: boolean) => void;
}

function readFramework(): CastFramework | null {
  if (typeof window === "undefined") return null;
  return window.cast?.framework ?? null;
}

function readChrome(): ChromeCast | null {
  if (typeof window === "undefined") return null;
  return window.chrome?.cast ?? null;
}

function statusFromSdk(fw: CastFramework): CastStatus {
  const state = fw.CastContext.getInstance().getCastState();
  switch (state) {
    case fw.CastState.NO_DEVICES_AVAILABLE:
      return "no_devices";
    case fw.CastState.NOT_CONNECTED:
      return "available";
    case fw.CastState.CONNECTING:
      return "connecting";
    case fw.CastState.CONNECTED:
      return "connected";
    default:
      return "available";
  }
}

export function useCast(): UseCastResult {
  const [status, setStatus] = useState<CastStatus>("unavailable");
  const [deviceName, setDeviceName] = useState<string | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const playerRef = useRef<cast.framework.RemotePlayer | null>(null);
  const controllerRef = useRef<cast.framework.RemotePlayerController | null>(
    null,
  );

  // Poll for SDK readiness. CastBootstrap loads the script asynchronously,
  // so a hook mounted on the watch page may run before window.cast exists.
  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    function tick() {
      if (cancelled) return;
      const fw = readFramework();
      if (!fw) {
        attempts += 1;
        // ~5 seconds of polling. If it's still not loaded by then, the user
        // is on a browser without Cast or the script was blocked.
        if (attempts > 50) {
          setStatus("unavailable");
          return;
        }
        window.setTimeout(tick, 100);
        return;
      }

      // Initial snapshot.
      setStatus(statusFromSdk(fw));
      const session = fw.CastContext.getInstance().getCurrentSession();
      if (session) {
        setDeviceName(session.getCastDevice()?.friendlyName ?? null);
      }

      // CastContext listeners for availability + connection transitions.
      const context = fw.CastContext.getInstance();
      const onCastState = () => {
        setStatus(statusFromSdk(fw));
        const current = context.getCurrentSession();
        setDeviceName(current?.getCastDevice()?.friendlyName ?? null);
      };
      const onSessionState = () => {
        setStatus(statusFromSdk(fw));
        const current = context.getCurrentSession();
        setDeviceName(current?.getCastDevice()?.friendlyName ?? null);
      };

      context.addEventListener(
        fw.CastContextEventType.CAST_STATE_CHANGED,
        onCastState,
      );
      context.addEventListener(
        fw.CastContextEventType.SESSION_STATE_CHANGED,
        onSessionState,
      );

      // RemotePlayer + Controller for mirrored media state.
      const player = new fw.RemotePlayer();
      const controller = new fw.RemotePlayerController(player);
      playerRef.current = player;
      controllerRef.current = controller;

      const onAnyChange = () => {
        setIsPaused(player.isPaused);
        setCurrentTime(player.currentTime || 0);
        setDuration(player.duration || 0);
      };
      controller.addEventListener(
        fw.RemotePlayerEventType.ANY_CHANGE,
        onAnyChange,
      );

      // Cleanup registered on the unmount effect below.
      cleanupRef.current = () => {
        context.removeEventListener(
          fw.CastContextEventType.CAST_STATE_CHANGED,
          onCastState,
        );
        context.removeEventListener(
          fw.CastContextEventType.SESSION_STATE_CHANGED,
          onSessionState,
        );
        controller.removeEventListener(
          fw.RemotePlayerEventType.ANY_CHANGE,
          onAnyChange,
        );
      };
    }

    const cleanupRef: { current: (() => void) | null } = { current: null };
    tick();

    return () => {
      cancelled = true;
      cleanupRef.current?.();
    };
  }, []);

  const loadMedia = useCallback(
    async ({
      contentUrl,
      contentType,
      title,
      subtitle,
      posterUrl,
      startTime,
      durationSec,
    }: CastMediaPayload) => {
      const fw = readFramework();
      const cc = readChrome();
      if (!fw || !cc) throw new Error("Cast SDK not loaded");

      const session = fw.CastContext.getInstance().getCurrentSession();
      if (!session) throw new Error("No active cast session");

      const info = new cc.media.MediaInfo(contentUrl, contentType);
      info.contentUrl = contentUrl;
      // HLS is served as VOD; MP4 direct-play is also VOD from the receiver's
      // perspective. "BUFFERED" is the correct streamType for both.
      info.streamType = "BUFFERED";
      if (typeof durationSec === "number") info.duration = durationSec;

      const metadata = new cc.media.GenericMediaMetadata();
      if (title) metadata.title = title;
      if (subtitle) metadata.subtitle = subtitle;
      if (posterUrl) metadata.images = [new cc.Image(posterUrl)];
      info.metadata = metadata;

      const request = new cc.media.LoadRequest(info);
      request.autoplay = true;
      if (typeof startTime === "number" && startTime > 0) {
        request.currentTime = startTime;
      }

      await session.loadMedia(request);
    },
    [],
  );

  const playPause = useCallback(() => {
    controllerRef.current?.playOrPause();
  }, []);

  const seek = useCallback((seconds: number) => {
    const player = playerRef.current;
    const controller = controllerRef.current;
    if (!player || !controller) return;
    player.currentTime = seconds;
    controller.seek();
  }, []);

  const stop = useCallback(() => {
    controllerRef.current?.stop();
  }, []);

  const endSession = useCallback((stopCasting = true) => {
    const fw = readFramework();
    if (!fw) return;
    const session = fw.CastContext.getInstance().getCurrentSession();
    session?.endSession(stopCasting);
  }, []);

  return {
    status,
    deviceName,
    isConnected: status === "connected",
    isPaused,
    currentTime,
    duration,
    loadMedia,
    playPause,
    seek,
    stop,
    endSession,
  };
}
