// One episode row for the show page and the season page: number, title,
// overview, runtime and progress (the row plays the episode), plus a 3-dot
// menu whose "File info" item shows that episode's own file (its first
// media_files entry): codec, bitrate, container, resolution, audio, size,
// path. Replaces the series-wide File Information card that showed a sample
// file from the first episode.

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MarkWatchedButton } from "@/components/MarkWatchedButton";
import { FileInfoMenuButton } from "@/components/FileInfoSheet";
import { formatDuration } from "@/lib/format";
import { useProgressMap } from "@/lib/progress";
import { useIsAdmin } from "@/lib/use-is-admin";
import type { Episode } from "@/lib/types";

export function EpisodeRow({ ep }: { ep: Episode }) {
  const primary = ep.media_files[0];
  const isAdmin = useIsAdmin();
  const progress = useProgressMap();
  const row = primary ? progress?.get(primary.id) : undefined;
  const [watched, setWatched] = useState<boolean | null>(null);
  const effective = watched ?? Boolean(row?.completed_at);
  useEffect(() => {
    if (progress && watched === null && primary) {
      setWatched(Boolean(row?.completed_at));
    }
  }, [progress, primary, row, watched]);

  const pct =
    row?.duration_sec && row.duration_sec > 0
      ? Math.round((row.position_sec / row.duration_sec) * 100)
      : null;
  const label = ep.title ?? `Episode ${ep.episode_number}`;

  const rowContent = (
    <>
      <div className="num">{String(ep.episode_number).padStart(2, "0")}</div>
      <div className="body">
        <div className="t">{label}</div>
        {ep.overview ? <div className="s">{ep.overview}</div> : null}
      </div>
      <div className="right">
        <div>{primary?.duration_sec ? formatDuration(primary.duration_sec) : "—"}</div>
        {pct !== null && pct > 0 && pct < 100 ? (
          <div className="pb">
            <div style={{ width: `${pct}%` }} />
          </div>
        ) : null}
        {effective ? (
          <span style={{ color: "var(--hive-text)", fontSize: 10 }}>watched</span>
        ) : null}
      </div>
    </>
  );

  if (!primary) {
    return (
      <div className="ep" style={{ opacity: 0.5 }}>
        {rowContent}
        <span />
      </div>
    );
  }

  return (
    <div className="ep">
      <Link
        href={`/watch/${primary.id}`}
        style={{ display: "contents" }}
        aria-label={`Play ${label}`}
      >
        {rowContent}
      </Link>
      <FileInfoMenuButton
        file={primary}
        label={`S${ep.season_number}E${ep.episode_number} ${label}`}
        isAdmin={isAdmin}
      />
      <span style={{ display: "none" }}>
        <MarkWatchedButton mediaFileId={primary.id} isWatched={effective} onChanged={setWatched} />
      </span>
    </div>
  );
}
