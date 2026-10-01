/** Pure helpers for the video subtitle/audio/quality pickers (crit 41). No
 * native imports so they unit test in Node. The VideoPlayer owns the React
 * state; these format labels and normalize choices passed to stream/start. */

import type { AudioStream, StreamQuality, SubtitleChoice, SubtitleStream } from "@/api/types";

export const QUALITIES: StreamQuality[] = ["original", "1080p", "720p", "480p"];

/** Human label for a quality value. */
export function qualityLabel(q: StreamQuality): string {
  return q === "original" ? "Original" : q;
}

/** Display label for an audio stream row. */
export function audioLabel(a: AudioStream): string {
  const parts: string[] = [];
  if (a.language) parts.push(a.language.toUpperCase());
  if (a.title) parts.push(a.title);
  if (a.codec) parts.push(a.codec.toUpperCase());
  if (a.channels) parts.push(a.channels === 2 ? "Stereo" : a.channels === 6 ? "5.1" : `${a.channels}ch`);
  const label = parts.join(" · ");
  return label || `Track ${a.index}`;
}

/** Display label for a subtitle stream row. */
export function subtitleLabel(s: SubtitleStream): string {
  const parts: string[] = [];
  if (s.language) parts.push(s.language.toUpperCase());
  if (s.title) parts.push(s.title);
  if (s.forced) parts.push("Forced");
  const label = parts.join(" · ");
  return label || `Subtitle ${s.index}`;
}

/** The default audio index to preselect: the stream flagged default, else the
 * first, else undefined (let the server decide). */
export function defaultAudioIndex(audio: AudioStream[]): number | undefined {
  if (audio.length === 0) return undefined;
  const def = audio.find((a) => a.default);
  return (def ?? audio[0]).index;
}

/** Whether a subtitle choice means "show a text track" (a numeric index that is
 * not a burn-in). Burn-in and "off" are handled server-side / by hiding. */
export function isTextSubtitle(choice: SubtitleChoice): choice is number {
  return typeof choice === "number";
}

/** Normalize a subtitle picker selection into the stream/start value. */
export function normalizeSubtitle(choice: SubtitleChoice | null | undefined): SubtitleChoice {
  if (choice == null) return "off";
  return choice;
}
