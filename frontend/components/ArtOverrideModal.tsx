// Admin modal for pinning an image override on an entity+role.
//
// Three input paths:
//   - Upload: pick a local file, multipart POST to the admin BFF.
//   - Paste URL: JSON POST to /from-url, backend fetches + validates.
//   - Search: tab-mount fetch hits the *arr aggregator at /search;
//     clicking a candidate POSTs {source, ref} to /from-search and the
//     backend re-derives the URL from a fresh aggregator call.
//
// On success the modal calls `onApplied()` and the parent re-fetches
// so the cache-busted image replaces the old one.
//
// Admin-gated: parents must only mount this when the current user is
// an admin. We don't re-check here to avoid a second /me round trip.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { X } from "lucide-react";
import { SourceCallouts, SourceTag } from "@/components/SourceTag";
import { candidateTileSrc, type ArtCandidate } from "@/lib/art-candidate";

export type ArtKind = "artist" | "movie" | "series" | "music_video" | "mix";
export type ArtRole = "thumb" | "poster" | "backdrop" | "cover";

type Props = {
  open: boolean;
  onClose: () => void;
  onApplied: () => void;
  entityKind: ArtKind;
  entityId: string;
  role: ArtRole;
  // Human-readable label for the dialog heading, e.g. "Nick Cave" or
  // "Breaking Bad - Poster". Falls back to "<kind> <role>" if omitted.
  title?: string;
  // Whether the entity already has an override. Controls the Remove
  // button visibility. The parent knows this from list/detail data.
  hasOverride?: boolean;
};

type Tab = "upload" | "url" | "search";

type Candidate = ArtCandidate;

// GET /search response: candidate tiles plus friendly notes about sources
// that did not answer or are not set up.
type ArtSearchResponse = {
  candidates: Candidate[];
  notes: string[];
};

export function ArtOverrideModal({
  open,
  onClose,
  onApplied,
  entityKind,
  entityId,
  role,
  title,
  hasOverride,
}: Props) {
  const [tab, setTab] = useState<Tab>("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [searchNotes, setSearchNotes] = useState<string[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // Tracks the (kind, id) we already kicked off a search fetch for, so
  // the search effect doesn't re-fire on its own state updates. Keying
  // on entity rather than a boolean lets a re-open against a different
  // entity refetch correctly.
  const fetchedKeyRef = useRef<string | null>(null);

  // Reset on open/close so a stale error or candidate list from a
  // previous session isn't what the admin sees next time.
  useEffect(() => {
    if (!open) {
      fetchedKeyRef.current = null;
      return;
    }
    setTab("upload");
    setBusy(false);
    setError(null);
    setUrl("");
    setCandidates(null);
    setSearchNotes([]);
    setSearchError(null);
    setSearchLoading(false);
    fetchedKeyRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }, [open, entityKind, entityId, role]);

  // Mix pictures fall back to a built-in default rather than "no override".
  const removeLabel = entityKind === "mix" ? "Reset to default" : "Remove override";
  const basePath = `/api/admin/art/${entityKind}/${entityId}/${role}`;

  // Tab-mount fetch: the spec is explicit that we don't debounce on
  // keystrokes. The aggregator is keyed on the entity, not a search
  // term, so one shot is enough. We dedupe via a ref instead of by
  // reading `candidates`/`searchLoading` from deps; including those in
  // the dep array caused the effect to re-fire after `setSearchLoading
  // (true)`, which cancelled the in-flight fetch and left the modal
  // stuck on the skeleton state.
  useEffect(() => {
    if (!open) return;
    if (tab !== "search") return;
    const key = `${entityKind}:${entityId}`;
    if (fetchedKeyRef.current === key) return;
    fetchedKeyRef.current = key;
    let cancelled = false;
    (async () => {
      setSearchLoading(true);
      setSearchError(null);
      try {
        const res = await fetch(
          `/api/admin/art/search?kind=${encodeURIComponent(entityKind)}&id=${encodeURIComponent(entityId)}`,
          { cache: "no-store" },
        );
        if (cancelled) return;
        if (!res.ok) {
          setSearchError(await extractError(res));
          setCandidates([]);
          return;
        }
        const body = (await res.json()) as ArtSearchResponse;
        if (!cancelled) {
          setCandidates(Array.isArray(body.candidates) ? body.candidates : []);
          setSearchNotes(Array.isArray(body.notes) ? body.notes : []);
        }
      } catch (err) {
        if (!cancelled) {
          setSearchError(err instanceof Error ? err.message : "Search failed.");
          setCandidates([]);
        }
      } finally {
        if (!cancelled) setSearchLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, tab, entityKind, entityId]);

  const handleUpload = useCallback(async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Pick a file first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(basePath, { method: "POST", body });
      if (!res.ok) {
        setError(await extractError(res));
        return;
      }
      onApplied();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }, [basePath, onApplied, onClose]);

  const handleFromUrl = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setError("Paste a URL first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${basePath}/from-url`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) {
        setError(await extractError(res));
        return;
      }
      onApplied();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed.");
    } finally {
      setBusy(false);
    }
  }, [basePath, onApplied, onClose, url]);

  const handlePickCandidate = useCallback(
    async (candidate: Candidate) => {
      setBusy(true);
      setError(null);
      try {
        const res = await fetch(`${basePath}/from-search`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            source: candidate.source,
            ref: candidate.ref,
          }),
        });
        if (!res.ok) {
          setError(await extractError(res));
          return;
        }
        onApplied();
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Apply failed.");
      } finally {
        setBusy(false);
      }
    },
    [basePath, onApplied, onClose],
  );

  const handleRemove = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(basePath, { method: "DELETE" });
      if (!res.ok && res.status !== 404) {
        setError(await extractError(res));
        return;
      }
      onApplied();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remove failed.");
    } finally {
      setBusy(false);
    }
  }, [basePath, onApplied, onClose]);

  if (!open) return null;

  const heading = title ?? `${entityKind} ${role}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="art-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* The panel is capped at the screen height (the overlay's p-4 is the
          1rem either side). Header and tabs stay put; only the body scrolls. */}
      <div className="flex max-h-[calc(100dvh-2rem)] w-full max-w-lg flex-col rounded-lg bg-neutral-900 shadow-xl ring-1 ring-neutral-800">
        <div className="flex shrink-0 items-center justify-between border-b border-neutral-800 px-5 py-3">
          <h2
            id="art-modal-title"
            className="text-sm font-medium tracking-tight text-neutral-100"
          >
            Edit art - {heading}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
            aria-label="Close"
          >
            <Icon icon={X} size={16} />
          </button>
        </div>

        <div className="flex shrink-0 gap-2 border-b border-neutral-800 px-5 pt-3">
          <TabButton active={tab === "upload"} onClick={() => setTab("upload")}>
            Upload
          </TabButton>
          <TabButton active={tab === "url"} onClick={() => setTab("url")}>
            Paste URL
          </TabButton>
          {entityKind === "mix" ? null : (
            <TabButton active={tab === "search"} onClick={() => setTab("search")}>
              Search
            </TabButton>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
          {tab === "upload" ? (
            <div className="space-y-3">
              <p className="text-xs text-neutral-400">
                JPG, PNG, or WebP. Up to 10 MB.
              </p>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="block w-full text-sm text-neutral-300 file:mr-3 file:rounded file:border-0 file:bg-neutral-800 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-neutral-100 hover:file:bg-neutral-700"
              />
              <div className="flex justify-end gap-2 pt-2">
                {hasOverride ? (
                  <button
                    type="button"
                    onClick={handleRemove}
                    disabled={busy}
                    className="rounded px-3 py-1.5 text-sm text-red-300 hover:bg-red-950/40 disabled:opacity-50"
                  >
                    {removeLabel}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={handleUpload}
                  disabled={busy}
                  className="rounded bg-hive px-3 py-1.5 text-sm font-medium text-on-hive hover:bg-hive-hover disabled:opacity-50"
                >
                  {busy ? "Uploading..." : "Apply"}
                </button>
              </div>
            </div>
          ) : tab === "url" ? (
            <div className="space-y-3">
              <p className="text-xs text-neutral-400">
                Public https URL. Backend fetches and validates before saving.
              </p>
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://..."
                className="block w-full rounded border border-neutral-800 bg-neutral-950 px-3 py-1.5 text-sm text-neutral-100 placeholder-neutral-500 focus:border-ink focus:outline-none"
              />
              <div className="flex justify-end gap-2 pt-2">
                {hasOverride ? (
                  <button
                    type="button"
                    onClick={handleRemove}
                    disabled={busy}
                    className="rounded px-3 py-1.5 text-sm text-red-300 hover:bg-red-950/40 disabled:opacity-50"
                  >
                    {removeLabel}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={handleFromUrl}
                  disabled={busy}
                  className="rounded bg-hive px-3 py-1.5 text-sm font-medium text-on-hive hover:bg-hive-hover disabled:opacity-50"
                >
                  {busy ? "Fetching..." : "Apply"}
                </button>
              </div>
            </div>
          ) : (
            <SearchPanel
              candidates={candidates}
              notes={searchNotes}
              loading={searchLoading}
              error={searchError}
              busy={busy}
              hasOverride={Boolean(hasOverride)}
              onPick={handlePickCandidate}
              onRemove={handleRemove}
              removeLabel={removeLabel}
            />
          )}

          {error ? (
            <p className="mt-3 rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
              {error}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SearchPanel({
  candidates,
  notes,
  loading,
  error,
  busy,
  hasOverride,
  onPick,
  onRemove,
  removeLabel,
}: {
  candidates: Candidate[] | null;
  notes: string[];
  loading: boolean;
  error: string | null;
  busy: boolean;
  hasOverride: boolean;
  onPick: (c: Candidate) => void;
  onRemove: () => void;
  removeLabel: string;
}) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-neutral-400">
        Candidates from the sources set up for this entity. Click one to
        download and pin it.
      </p>
      {!loading && candidates !== null ? <SourceCallouts notes={notes} /> : null}
      {loading || candidates === null ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="aspect-[2/3] w-full animate-pulse rounded bg-neutral-800"
            />
          ))}
        </div>
      ) : error ? (
        <p className="rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          {error}
        </p>
      ) : candidates.length === 0 ? (
        <p className="rounded border border-neutral-800 bg-neutral-950/60 px-3 py-3 text-xs text-neutral-400">
          No candidates returned. Try Upload or Paste URL.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {candidates.map((c) => (
            <button
              key={`${c.source}:${c.ref}`}
              type="button"
              onClick={() => onPick(c)}
              disabled={busy}
              className="group flex flex-col items-stretch overflow-hidden rounded border border-neutral-800 bg-neutral-950 text-left transition hover:border-hive focus:outline-none focus:ring-1 focus:ring-focus disabled:opacity-50"
              aria-label={`Apply ${c.label}`}
            >
              <CandidateImage candidate={c} />
              <div className="flex items-center justify-between gap-1 px-2 py-1">
                <span className="line-clamp-1 text-[10px] uppercase tracking-wide text-neutral-400 group-hover:text-neutral-200">
                  {c.label}
                </span>
                <SourceTag source={c.source} />
              </div>
            </button>
          ))}
        </div>
      )}
      {hasOverride ? (
        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={onRemove}
            disabled={busy}
            className="rounded px-3 py-1.5 text-sm text-red-300 hover:bg-red-950/40 disabled:opacity-50"
          >
            {removeLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}

// Tile image: loads the small preview, never the full-size apply URL. If the
// preview fails to load it tries the full URL once before giving up.
function CandidateImage({ candidate }: { candidate: Candidate }) {
  const preview = candidateTileSrc(candidate);
  const [src, setSrc] = useState(preview);
  return (
    <div className="aspect-[2/3] w-full overflow-hidden bg-neutral-900">
      <img
        src={src}
        alt={candidate.label}
        loading="lazy"
        decoding="async"
        onError={() => {
          if (src !== candidate.url) setSrc(candidate.url);
        }}
        className="h-full w-full object-cover"
      />
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-t px-3 py-1.5 text-sm ${
        active
          ? "border-b-2 border-hive text-neutral-100"
          : "text-neutral-400 hover:text-neutral-200"
      }`}
    >
      {children}
    </button>
  );
}

async function extractError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // fall through
  }
  return `HTTP ${res.status}`;
}
