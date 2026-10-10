// Admin-only "Merge into..." dialog, shared by the Music artist tile 3-dot
// menu and the artist detail page. Two steps: pick a target artist, then a
// confirm that NAMES what moves (how many albums and tracks go to the target).
// On success the source artist is gone and a durable alias is saved server-side
// so a rescan or Lidarr sync does not recreate it.

"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import type { MusicArtist } from "@/lib/types";

type Preview = {
  source_id: string;
  source_name: string;
  target_id: string;
  target_name: string;
  albums: number;
  tracks: number;
};

type MergeResult = {
  merge_id: string;
  target_id: string;
  target_name: string;
  albums_moved: number;
  tracks_moved: number;
};

export function ArtistMergeDialog({
  sourceId,
  sourceName,
  onClose,
  onMerged,
}: {
  sourceId: string;
  sourceName: string;
  onClose: () => void;
  // Called after a successful merge so the caller can refresh / navigate.
  onMerged: (result: MergeResult) => void;
}) {
  const [artists, setArtists] = useState<MusicArtist[] | null>(null);
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<MusicArtist | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<MusicArtist[]>("/api/library/artists");
        if (!cancelled) setArtists(data.filter((a) => a.id !== sourceId));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load artists");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  const filtered = useMemo(() => {
    if (!artists) return null;
    const q = query.trim().toLowerCase();
    if (!q) return artists.slice(0, 60);
    return artists.filter((a) => a.name.toLowerCase().includes(q)).slice(0, 60);
  }, [artists, query]);

  async function pickTarget(a: MusicArtist) {
    setTarget(a);
    setPreview(null);
    setError(null);
    try {
      const p = await apiGet<Preview>(
        `/api/admin/artists/${sourceId}/merge-preview?target_id=${encodeURIComponent(a.id)}`,
      );
      setPreview(p);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Could not read what would move (${err.status}).`
          : "Could not read what would move.",
      );
    }
  }

  async function confirmMerge() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<MergeResult>(
        `/api/admin/artists/${sourceId}/merge`,
        { target_id: target.id },
      );
      onMerged(result);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Merge failed (${err.status}).`
          : "Merge failed.",
      );
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Merge ${sourceName} into another artist`}
      style={overlayStyle}
      onClick={(e) => {
        // The dialog can be a descendant of an artist card <Link>; keep a
        // backdrop click from navigating.
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        style={panelStyle}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <h2 style={titleStyle}>Merge artist</h2>
        <p style={subtitleStyle}>
          Move everything under <strong>{sourceName}</strong> onto another
          artist. The merge is saved so a rescan does not bring it back.
        </p>

        {target && preview ? (
          <div style={confirmStyle}>
            <p style={{ margin: "0 0 10px" }}>
              Merge <strong>{preview.source_name}</strong> into{" "}
              <strong>{preview.target_name}</strong>?
            </p>
            <p style={{ margin: "0 0 14px", color: "var(--ink-2)" }}>
              {preview.albums} {preview.albums === 1 ? "album" : "albums"} and{" "}
              {preview.tracks} {preview.tracks === 1 ? "track" : "tracks"} move
              to {preview.target_name}. {preview.source_name} is then removed.
            </p>
            <div style={rowStyle}>
              <button
                type="button"
                style={ghostBtn}
                onClick={() => {
                  setTarget(null);
                  setPreview(null);
                }}
                disabled={busy}
              >
                Back
              </button>
              <button
                type="button"
                style={dangerBtn}
                onClick={confirmMerge}
                disabled={busy}
              >
                {busy ? "Merging..." : "Merge"}
              </button>
            </div>
          </div>
        ) : (
          <>
            <input
              type="text"
              placeholder="Search artists..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={inputStyle}
              autoFocus
            />
            <div style={listStyle}>
              {filtered === null ? (
                <div style={{ padding: 12, color: "var(--ink-3)" }}>Loading...</div>
              ) : filtered.length === 0 ? (
                <div style={{ padding: 12, color: "var(--ink-3)" }}>No matches.</div>
              ) : (
                filtered.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    style={itemStyle}
                    onClick={() => pickTarget(a)}
                  >
                    {a.name}
                    <span style={{ color: "var(--ink-3)", marginLeft: 8 }}>
                      {a.album_count} {a.album_count === 1 ? "album" : "albums"}
                    </span>
                  </button>
                ))
              )}
            </div>
            <div style={rowStyle}>
              <button type="button" style={ghostBtn} onClick={onClose}>
                Cancel
              </button>
            </div>
          </>
        )}

        {error ? (
          <div role="alert" style={errorStyle}>
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.6)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
  padding: 16,
};
const panelStyle: CSSProperties = {
  width: "min(480px, 100%)",
  maxHeight: "80vh",
  overflowY: "auto",
  background: "var(--bg-2)",
  border: "1px solid var(--line)",
  borderRadius: 6,
  padding: 20,
  fontFamily: "var(--grotesk)",
  color: "var(--ink-1)",
};
const titleStyle: CSSProperties = { margin: "0 0 6px", fontSize: 18 };
const subtitleStyle: CSSProperties = {
  margin: "0 0 14px",
  fontSize: 13,
  color: "var(--ink-2)",
};
const inputStyle: CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  background: "var(--surface-2)",
  border: "1px solid var(--line)",
  borderRadius: 4,
  color: "var(--ink-1)",
  fontFamily: "inherit",
  fontSize: 14,
  marginBottom: 10,
};
const listStyle: CSSProperties = {
  maxHeight: "40vh",
  overflowY: "auto",
  border: "1px solid var(--line)",
  borderRadius: 4,
  marginBottom: 14,
};
const itemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  textAlign: "left",
  padding: "8px 12px",
  background: "transparent",
  border: "none",
  borderBottom: "1px solid var(--line-soft)",
  color: "var(--ink-1)",
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 14,
};
const confirmStyle: CSSProperties = { fontSize: 14 };
const rowStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 10,
};
const ghostBtn: CSSProperties = {
  padding: "8px 16px",
  background: "transparent",
  border: "1px solid var(--line)",
  borderRadius: 4,
  color: "var(--ink-1)",
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 14,
};
const dangerBtn: CSSProperties = {
  padding: "8px 16px",
  background: "var(--danger)",
  border: "1px solid var(--danger)",
  borderRadius: 4,
  color: "#fff",
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 14,
};
const errorStyle: CSSProperties = {
  marginTop: 12,
  color: "var(--danger)",
  fontFamily: "var(--mono)",
  fontSize: 12,
};
