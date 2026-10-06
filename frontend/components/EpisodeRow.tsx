// One episode row for the show page and the season page: number, title,
// overview, runtime and progress (the row plays the episode), plus a 3-dot
// menu whose "File info" item shows that episode's own file (its first
// media_files entry): codec, bitrate, container, resolution, audio, size,
// path. Replaces the series-wide File Information card that showed a sample
// file from the first episode.

"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { MoreVertical, X } from "lucide-react";
import { Icon } from "@/components/Icon";
import { MarkWatchedButton } from "@/components/MarkWatchedButton";
import { fileInfoRows } from "@/lib/file-info";
import { formatDuration } from "@/lib/format";
import { useProgressMap } from "@/lib/progress";
import type { Episode, MediaFile } from "@/lib/types";

export function EpisodeRow({ ep }: { ep: Episode }) {
  const primary = ep.media_files[0];
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
      <EpisodeFileMenu file={primary} episodeLabel={`S${ep.season_number}E${ep.episode_number} ${label}`} />
      <span style={{ display: "none" }}>
        <MarkWatchedButton mediaFileId={primary.id} isWatched={effective} onChanged={setWatched} />
      </span>
    </div>
  );
}

function EpisodeFileMenu({ file, episodeLabel }: { file: MediaFile; episodeLabel: string }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!infoOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setInfoOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [infoOpen]);

  return (
    <div ref={ref} className="ep-menu">
      <button
        type="button"
        className="ep-menu-btn"
        aria-label={`${episodeLabel} actions`}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((v) => !v)}
      >
        <Icon icon={MoreVertical} size={18} />
      </button>
      {menuOpen ? (
        <div role="menu" className="ep-menu-pop">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setInfoOpen(true);
            }}
          >
            File info
          </button>
        </div>
      ) : null}
      {infoOpen ? (
        <div className="ep-info-scrim" onClick={() => setInfoOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={`File info: ${episodeLabel}`}
            className="card font-sans ep-info"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="ep-info-head">
              <h4>File info</h4>
              <button type="button" aria-label="Close" onClick={() => setInfoOpen(false)}>
                <Icon icon={X} size={16} />
              </button>
            </div>
            <div className="ep-info-sub">{episodeLabel}</div>
            {fileInfoRows(file).map((r) => (
              <div className="row" key={r.label}>
                <span>{r.label}</span>
                <span style={r.label === "File path" ? { fontSize: 11 } : undefined}>{r.value}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
