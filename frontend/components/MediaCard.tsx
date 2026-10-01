// A single tappable library tile in the Marquee design. Renders a
// theatrical 2:3 poster (or 1:1 for albums/artists) with a tinted gradient
// placeholder driven by --pg, plus a title + meta line below.
//
// `status` paints a small watched check or a thin amber progress bar. The
// admin Edit affordance opts the tile into a hover-revealed Edit button
// over the poster; the parent page is responsible for gating the prop on
// the admin role.

"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import { Poster } from "./Poster";
import { colorForTitle, hueFromString } from "@/lib/format";
import type { FileStatus } from "@/lib/progress";

type Kind = "movie" | "series" | "album" | "track" | "music_video" | "music_video_release";

type Props = {
  href: string;
  title: string;
  subtitle?: string | null;
  posterPath: string | null;
  kind: Kind;
  status?: FileStatus;
  progressPct?: number;
  onAdminEdit?: () => void;
  adminEditLabel?: string;
  // When provided, a hover-revealed play button is painted over the
  // frame. The handler is responsible for resolving the item(s) and
  // pushing them into the queue.
  onPlay?: () => void;
  // Extra chrome anchored over the tile (e.g. a context menu). Rendered
  // as a sibling of the frame so its own absolute positioning resolves
  // against the .poster wrapper and is not clipped by the frame's
  // overflow:hidden.
  overlay?: React.ReactNode;
};

export function MediaCard({
  href,
  title,
  subtitle,
  posterPath,
  kind,
  status,
  progressPct,
  onAdminEdit,
  adminEditLabel,
  onPlay,
  overlay,
}: Props) {
  const aspect: "poster" | "square" =
    kind === "album" || kind === "track" || kind === "music_video_release"
      ? "square"
      : "poster";
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(title),
    ["--ph" as never]: String(hueFromString(title)),
  };

  return (
    <Link
      href={href}
      className="poster"
      style={tint}
      aria-label={title}
    >
      <div
        className="frame"
        style={{
          aspectRatio: aspect === "square" ? "1/1" : "2/3",
        }}
      >
        <div className="keyart-mini" />
        {posterPath ? (
          <img
            src={posterPath}
            alt={title}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
        {status === "watched" ? (
          <div className="watched" aria-label="Watched" title="Watched">
            <CheckIcon />
          </div>
        ) : null}
        {status === "in_progress" && typeof progressPct === "number" ? (
          <div className="progress">
            <div style={{ width: `${Math.max(0, Math.min(100, progressPct))}%` }} />
          </div>
        ) : null}
        {onAdminEdit ? (
          <button
            type="button"
            className="admin-edit"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onAdminEdit();
            }}
            aria-label={adminEditLabel ?? `Edit image for ${title}`}
          >
            Edit
          </button>
        ) : null}
        {onPlay ? (
          <button
            type="button"
            className="tile-play"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onPlay();
            }}
            aria-label={`Play ${title}`}
          >
            <PlayIcon />
          </button>
        ) : null}
      </div>
      <div className="info">
        <div className="t">{title}</div>
        {subtitle ? <div className="s">{subtitle}</div> : null}
      </div>
      {overlay}
    </Link>
  );
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

// Suppress the Poster import lint when not used directly.
void Poster;

function CheckIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 12l5 5L20 6" />
    </svg>
  );
}
