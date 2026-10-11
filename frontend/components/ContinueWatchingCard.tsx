// Continue Watching card for the home rail. Renders the wide 16:9 frame
// from the .continue-rail .poster style, deeplinks to /watch/<file_id>
// to resume in one tap, and shows remaining time in the bottom-left of
// the frame.

import Link from "next/link";
import type { CSSProperties } from "react";
import { colorForTitle, formatDuration, hueFromString } from "@/lib/format";
import type { ContinueWatchingItem } from "@/lib/types";
import { artSized } from "@/lib/art-url";

type Props = {
  item: ContinueWatchingItem;
};

export function ContinueWatchingCard({ item }: Props) {
  const duration = item.duration_sec;
  const pct = duration && duration > 0
    ? Math.min(100, Math.round((item.position_sec / duration) * 100))
    : 0;
  const remaining = duration ? Math.max(0, duration - item.position_sec) : null;
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(item.title),
    ["--ph" as never]: String(hueFromString(item.title)),
  };
  const subtitleParts = [
    item.subtitle ?? null,
    remaining ? `${formatDuration(remaining)} left` : null,
  ];
  const subtitle = subtitleParts
    .filter((s): s is string => !!s && s.trim().length > 0)
    .join(" • ");

  return (
    <Link
      href={`/watch/${item.media_file_id}`}
      className="poster"
      style={tint}
      aria-label={`Resume ${item.title}`}
    >
      <div className="frame" style={{ aspectRatio: "16/9" }}>
        <div className="keyart-mini" />
        {item.poster_path ? (
          <img
            src={artSized(item.poster_path, 600) ?? item.poster_path}
            alt={item.title}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
        <div className="resume-overlay">
          <div className="pp">
            <span className="tri" />
          </div>
        </div>
        {remaining != null ? (
          <div className="left-time">{formatDuration(remaining)} left</div>
        ) : null}
        <div className="progress">
          <div style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="info">
        <div className="t">{item.title}</div>
        {subtitle ? <div className="s">{subtitle}</div> : null}
      </div>
    </Link>
  );
}
