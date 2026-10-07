// Music — flat-track index. Substring-searchable list of every track,
// alphabetical by title. Row click plays via the dock; the shared row 3-dot
// menu (TrackRowMenu) offers Play now, Play next and Add to queue.

"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { AlphaRail, alphaLetterOf } from "@/components/AlphaRail";
import { GridEmpty } from "@/components/Grid";
import { TrackRowMenu } from "@/components/TrackRowMenu";
import { apiGet, ApiError } from "@/lib/client-api";
import { formatDuration } from "@/lib/format";
import { songRowToQueueItem, useQueue } from "@/lib/queue";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import type { SongRow } from "@/lib/types";
import { useViewPref } from "@/lib/use-view-pref";

const DEBOUNCE_MS = 200;
const FETCH_LIMIT = 2000;

export default function MusicSongsPage() {
  return (
    <Suspense fallback={<SongsShell />}>
      <SongsPageInner />
    </Suspense>
  );
}

function SongsShell() {
  return (
    <AuthShell>
      <h1 className="page-title">Music</h1>
      <div className="filter-bar">
        <span className="lbl">Browse</span>
        <Link href="/music" className="chip">Artists</Link>
        <Link href="/music/albums" className="chip">Albums</Link>
        <span className="chip on">Songs</span>
      </div>
    </AuthShell>
  );
}

function SongsPageInner() {
  useScrollRestoration();
  // Saved view: being on Songs makes it the Music browse tab (stored on the
  // server per user), once per visit.
  const [browse, setBrowse, browseLoaded] = useViewPref("music.browse");
  const markedRef = useRef(false);
  useEffect(() => {
    if (!browseLoaded || markedRef.current) return;
    markedRef.current = true;
    if (browse !== "songs") setBrowse("songs");
  }, [browseLoaded, browse, setBrowse]);
  const router = useRouter();
  const params = useSearchParams();
  const initialQ = params.get("q") ?? "";

  const [query, setQuery] = useState(initialQ);
  const [songs, setSongs] = useState<SongRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    const next = new URLSearchParams();
    if (q) next.set("q", q);
    const suffix = next.toString();
    router.replace(suffix ? `/music/songs?${suffix}` : "/music/songs");
  }, [query, router]);

  useEffect(() => {
    const controller = new AbortController();
    const q = query.trim();
    const timer = window.setTimeout(async () => {
      setSongs(null);
      setError(null);
      try {
        const qs = new URLSearchParams({ limit: String(FETCH_LIMIT) });
        if (q) qs.set("q", q);
        const data = await apiGet<SongRow[]>(
          `/api/library/songs?${qs.toString()}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setSongs(data);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError) {
          setError(err.message);
        } else if (err instanceof Error) {
          if (err.name === "AbortError") return;
          setError(err.message);
        } else {
          setError("Failed to load songs.");
        }
        setSongs([]);
      }
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  return (
    <AuthShell>
      <h1 className="page-title">Music</h1>

      <div className="filter-bar">
        <span className="lbl">Browse</span>
        <Link href="/music" className="chip" onClick={() => setBrowse("artists")}>Artists</Link>
        <Link href="/music/albums" className="chip" onClick={() => setBrowse("albums")}>Albums</Link>
        <span className="chip on">Songs</span>
      </div>

      <div
        style={{
          padding: "16px 24px 8px",
          maxWidth: 1200,
          margin: "0 auto",
          width: "100%",
        }}
      >
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search songs"
          spellCheck={false}
          autoComplete="off"
          aria-label="Search songs"
          style={{
            width: "100%",
            padding: "10px 14px",
            fontFamily: "var(--grotesk)",
            fontSize: 14,
            color: "var(--ink-1)",
            background: "var(--bg-2)",
            border: "1px solid var(--line)",
            borderRadius: 4,
            outline: "none",
          }}
        />
      </div>

      {error ? (
        <GridEmpty message={error} />
      ) : songs === null ? (
        <SongListSkeleton />
      ) : songs.length === 0 ? (
        <GridEmpty message="No songs match your search." />
      ) : (
        <SongList songs={songs} />
      )}

      <AlphaRail
        containerSelector=".songs-list"
        resetKey={`songs:${query.trim()}:${songs ? songs.length : 0}`}
      />
    </AuthShell>
  );
}

function SongListSkeleton() {
  return (
    <div
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        width: "100%",
        padding: "0 24px",
      }}
    >
      {Array.from({ length: 12 }).map((_, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "8px 0",
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              background: "var(--surface-2)",
              borderRadius: 3,
              flex: "0 0 40px",
            }}
          />
          <div
            style={{
              flex: 1,
              height: 14,
              background: "var(--surface-2)",
              borderRadius: 3,
            }}
          />
          <div
            style={{
              width: 80,
              height: 12,
              background: "var(--surface-2)",
              borderRadius: 3,
            }}
          />
        </div>
      ))}
    </div>
  );
}

function SongList({ songs }: { songs: SongRow[] }) {
  return (
    <div
      className="songs-list"
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        width: "100%",
        padding: "0 24px 80px",
      }}
    >
      {songs.map((row) => (
        <SongRowItem key={row.id} row={row} />
      ))}
    </div>
  );
}

function SongRowItem({ row }: { row: SongRow }) {
  const { playNow } = useQueue();

  const playable = row.media_files.length > 0;
  const queueItem = playable ? songRowToQueueItem(row) : null;

  function onRowClick() {
    if (queueItem) playNow(queueItem);
  }

  const initial = row.title?.[0]?.toUpperCase() ?? "?";

  return (
    <div
      data-alpha-letter={alphaLetterOf(row.title)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "6px 0",
        borderBottom: "1px solid var(--line)",
        position: "relative",
      }}
    >
      <button
        type="button"
        onClick={onRowClick}
        disabled={!playable}
        aria-label={
          playable
            ? `Play ${row.title}`
            : `${row.title} (no playable file)`
        }
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flex: "0 0 auto",
          minWidth: 0,
          padding: "4px 0",
          background: "transparent",
          border: "none",
          color: "inherit",
          textAlign: "left",
          cursor: playable ? "pointer" : "default",
          opacity: playable ? 1 : 0.55,
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            flex: "0 0 40px",
            background: "var(--surface-2)",
            borderRadius: 3,
            position: "relative",
            overflow: "hidden",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--grotesk)",
            fontSize: 14,
            color: "var(--ink-3)",
          }}
        >
          {row.cover_path ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={row.cover_path}
              alt=""
              loading="lazy"
              decoding="async"
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                objectFit: "cover",
              }}
            />
          ) : (
            <span aria-hidden>{initial}</span>
          )}
        </div>
      </button>
      <button
        type="button"
        onClick={onRowClick}
        disabled={!playable}
        aria-hidden
        tabIndex={-1}
        style={{
          flex: 1,
          minWidth: 0,
          fontFamily: "var(--grotesk)",
          fontSize: 14,
          color: "var(--ink-1)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          background: "transparent",
          border: "none",
          textAlign: "left",
          padding: "4px 0",
          cursor: playable ? "pointer" : "default",
          opacity: playable ? 1 : 0.55,
        }}
      >
        {row.title}
      </button>
      <TrackInfoLink href={`/music/artists/${row.artist_id}`}>
        {row.artist_name}
      </TrackInfoLink>
      <TrackInfoLink href={`/music/${row.album_id}`}>
        {row.album_title}
      </TrackInfoLink>
      <div
        style={{
          flex: "0 0 64px",
          textAlign: "right",
          fontFamily: "var(--mono)",
          fontSize: 12,
          color: "var(--ink-3)",
        }}
      >
        {formatDuration(row.duration_sec)}
      </div>

      <TrackRowMenu item={queueItem} label={row.title} />
    </div>
  );
}

function TrackInfoLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const [hover, setHover] = useState(false);
  return (
    <Link
      href={href}
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        flex: "0 1 220px",
        minWidth: 0,
        fontFamily: "var(--grotesk)",
        fontSize: 13,
        color: hover ? "var(--ink-1)" : "var(--ink-3)",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
        textDecoration: hover ? "underline" : "none",
      }}
    >
      {children}
    </Link>
  );
}
