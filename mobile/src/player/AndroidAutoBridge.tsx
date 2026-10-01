import { requireOptionalNativeModule } from "expo-modules-core";
import { useEffect, useRef } from "react";
import { Platform } from "react-native";
import TrackPlayer, { Event, State } from "react-native-track-player";

import { fetchMixSongs, MIXES } from "@/api/queries";
import type { AlbumDetail, Album, ArtistDetail, Artist, SongRow } from "@/api/types";
import { useDownloads } from "@/download/DownloadProvider";
import { downloadToSong } from "@/download/entries";
import { doneItems } from "@/download/queue";
import { useApi } from "@/state/auth";
import {
  folderId,
  parseParent,
  parsePlayableId,
  songItems,
  type AutoItem,
} from "./browseTree";
import { usePlayer } from "./PlayerProvider";

/** Native side: modules/f7five0-auto (F7FIVE0BrowserService + F7FIVE0AutoModule). */
interface F7FIVE0AutoNative {
  setChildren(parentId: string, itemsJson: string): boolean;
  setState(stateJson: string): boolean;
  isCarConnected(): boolean;
  addListener(event: string, cb: (e: Record<string, unknown>) => void): { remove(): void };
}

function albumSongs(d: AlbumDetail): SongRow[] {
  return d.tracks.map((t) => ({
    id: t.id,
    title: t.title,
    track_number: t.track_number,
    disc_number: t.disc_number,
    duration_sec: t.duration_sec,
    album_id: d.id,
    album_title: d.title,
    cover_path: d.cover_path,
    artist_id: d.artist_id,
    artist_name: d.artist_name ?? "",
    media_files: t.media_files,
  }));
}

function stateName(s: State | undefined): string {
  switch (s) {
    case State.Playing:
      return "playing";
    case State.Paused:
    case State.Ready:
      return "paused";
    case State.Buffering:
    case State.Loading:
      return "buffering";
    case State.Stopped:
    case State.Ended:
      return "stopped";
    case State.Error:
      return "error";
    default:
      return "none";
  }
}

/** Android Auto (spec J, criterion 44). Serves the browse tree the native
 * F7FIVE0BrowserService shows in the car (Home, Recently Played, Mixes, Albums,
 * Artists, Downloads), turns car transport commands into player actions, and
 * mirrors playback state to the car's session. Renders nothing; a no-op where
 * the native module isn't built in (TV, tests). */
export function AndroidAutoBridge(): null {
  const api = useApi();
  const player = usePlayer();
  const downloads = useDownloads();
  const playerRef = useRef(player);
  playerRef.current = player;
  const downloadsRef = useRef(downloads);
  downloadsRef.current = downloads;
  // Song lists by list key, so a car tap queues the whole list like the app.
  const lists = useRef(new Map<string, SongRow[]>());

  useEffect(() => {
    if (Platform.OS !== "android" || Platform.isTV) return;
    const native = requireOptionalNativeModule<F7FIVE0AutoNative>("F7FIVE0Auto");
    if (!native) return;

    const songsFor = async (listKey: string): Promise<SongRow[]> => {
      const cached = lists.current.get(listKey);
      if (cached) return cached;
      let songs: SongRow[] = [];
      const ref = parseParent(listKey);
      if (listKey === "home") songs = await fetchMixSongs(api, "continue-listening");
      else if (listKey === "recent") songs = await fetchMixSongs(api, "recently-played");
      else if (listKey === "downloads") songs = doneItems(downloadsRef.current.state, "track").map(downloadToSong);
      else if (ref?.kind === "mix") songs = await fetchMixSongs(api, ref.slug);
      else if (ref?.kind === "album") songs = albumSongs(await api.json<AlbumDetail>(`/api/albums/${ref.id}`));
      lists.current.set(listKey, songs);
      return songs;
    };

    const childrenFor = async (parentId: string): Promise<AutoItem[]> => {
      const ref = parseParent(parentId);
      if (!ref) return [];
      if (ref.kind === "category") {
        switch (ref.source.kind) {
          case "home":
          case "recent":
          case "downloads": {
            lists.current.delete(parentId);
            return songItems(parentId, await songsFor(parentId));
          }
          case "mixes":
            return MIXES.map((m) => ({ id: folderId.mix(m.id), title: m.title, subtitle: m.subtitle, browsable: true }));
          case "albums": {
            const albums = await api.json<Album[]>("/api/albums");
            return albums.slice(0, 300).map((a) => ({
              id: folderId.album(a.id),
              title: a.title,
              subtitle: a.artist_name ?? null,
              browsable: true,
            }));
          }
          case "artists": {
            const artists = await api.json<Artist[]>("/api/artists");
            return artists.slice(0, 300).map((a) => ({ id: folderId.artist(a.id), title: a.name, browsable: true }));
          }
        }
      }
      if (ref.kind === "artist") {
        const d = await api.json<ArtistDetail>(`/api/artists/${ref.id}`);
        return d.albums.map((a) => ({ id: folderId.album(a.id), title: a.title, browsable: true }));
      }
      // mix / album folders are song lists
      lists.current.delete(parentId);
      return songItems(parentId, await songsFor(parentId));
    };

    const onLoad = native.addListener("onAutoLoadChildren", (e) => {
      const parentId = String(e.parentId ?? "");
      void childrenFor(parentId)
        .catch(() => [] as AutoItem[])
        .then((items) => native.setChildren(parentId, JSON.stringify(items)));
    });

    const onCommand = native.addListener("onAutoCommand", (e) => {
      const p = playerRef.current;
      switch (e.command) {
        case "play":
          void TrackPlayer.play();
          break;
        case "pause":
          void TrackPlayer.pause();
          break;
        case "stop":
          void TrackPlayer.stop();
          break;
        case "next":
          void p.next();
          break;
        case "previous":
          void p.previous();
          break;
        case "seek":
          if (typeof e.positionMs === "number") void p.seekTo(e.positionMs / 1000);
          break;
        case "playFromMediaId": {
          const parsed = parsePlayableId(String(e.mediaId ?? ""));
          if (!parsed) break;
          void songsFor(parsed.listKey)
            .then((songs) => {
              if (songs.length > 0) return p.playSongs(songs, Math.min(parsed.index, songs.length - 1));
            })
            .catch(() => undefined);
          break;
        }
      }
    });

    // Mirror playback state + metadata to the car session.
    const push = async () => {
      try {
        const [state, track, progress] = await Promise.all([
          TrackPlayer.getPlaybackState(),
          TrackPlayer.getActiveTrack(),
          TrackPlayer.getProgress(),
        ]);
        native.setState(
          JSON.stringify({
            state: stateName(state.state),
            positionMs: Math.round((progress.position ?? 0) * 1000),
            durationMs: Math.round((progress.duration ?? track?.duration ?? 0) * 1000),
            title: track?.title ?? "",
            artist: track?.artist ?? "",
            album: track?.album ?? "",
            artUri: typeof track?.artwork === "string" ? track.artwork : "",
          }),
        );
      } catch {
        /* player not set up yet */
      }
    };
    const subs = [
      TrackPlayer.addEventListener(Event.PlaybackState, () => void push()),
      TrackPlayer.addEventListener(Event.PlaybackActiveTrackChanged, () => void push()),
    ];
    const timer = setInterval(() => {
      if (native.isCarConnected()) void push();
    }, 5000);

    return () => {
      onLoad.remove();
      onCommand.remove();
      subs.forEach((s) => s.remove());
      clearInterval(timer);
    };
  }, [api]);

  return null;
}
