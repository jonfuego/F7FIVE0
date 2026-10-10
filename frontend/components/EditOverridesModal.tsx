// Unified Edit Overrides modal. One Edit button per detail page opens
// this; five tabs cover General / Details / Art / Fix Match / Refresh.
//
// Save bar in General + Details PATCHes /api/admin/override/{kind}/{id}
// with only the dirty fields. Fix Match and Refresh have their own
// action buttons; the save bar is hidden on those tabs.
//
// Art tab stacks the existing ArtOverrideModal for per-role pickers
// rather than refactoring that component to expose its inner panel.
// The two modals coexist visually because each owns its own overlay.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { X } from "lucide-react";
import { ArtOverrideModal, ArtKind, ArtRole } from "@/components/ArtOverrideModal";
import { SourceCallouts, SourceTag } from "@/components/SourceTag";
import type {
  MatchCandidate,
  MatchCandidatesOut,
  OverrideKind,
  OverrideOut,
  OverrideUpdate,
} from "@/lib/types";

type TabId = "general" | "details" | "art" | "match" | "refresh";

type FieldState<T> = {
  value: T | null;
  dirty: boolean;
};

type DraftState = {
  display_name: FieldState<string>;
  sort_title: FieldState<string>;
  tagline: FieldState<string>;
  year: FieldState<number>;
  runtime_min: FieldState<number>;
  rating: FieldState<number>;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onApplied: () => void;
  kind: OverrideKind;
  entityId: string;
  initial: OverrideOut & { algorithmic_sort_hint: string };
};

const TABS: { id: TabId; label: string }[] = [
  { id: "general", label: "General" },
  { id: "details", label: "Details" },
  { id: "art", label: "Art" },
  { id: "match", label: "Fix Match" },
  { id: "refresh", label: "Refresh" },
];

// `runtime_min` only makes sense for video kinds. The Pydantic schema
// also rejects it for other kinds, so the Details tab hides the field
// when it would always 422.
const RUNTIME_KINDS = new Set<OverrideKind>(["movie", "series"]);

// Maps OverrideKind -> the ArtKind values the backend art surface
// supports. music_video_release has no admin/art route today, so the
// Art tab shows an explanatory note for that kind.
const ART_KIND_MAP: Partial<Record<OverrideKind, ArtKind>> = {
  movie: "movie",
  series: "series",
  artist: "artist",
};

export function algorithmicSortHint(title: string): string {
  return title.toLowerCase().replace(/^(the|a|an)\s+/, "");
}

export default function EditOverridesModal({
  open,
  onClose,
  onApplied,
  kind,
  entityId,
  initial,
}: Props) {
  const [tab, setTab] = useState<TabId>("general");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artModal, setArtModal] = useState<{ role: ArtRole } | null>(null);
  const [draft, setDraft] = useState<DraftState>(() => buildInitialDraft(initial));

  // Reset draft whenever the modal opens against a different entity. We
  // also clear stale tab errors so the next session starts clean.
  useEffect(() => {
    if (!open) return;
    setTab("general");
    setBusy(false);
    setError(null);
    setArtModal(null);
    setDraft(buildInitialDraft(initial));
  }, [open, entityId, kind, initial]);

  const dirtyAny = useMemo(
    () => Object.values(draft).some((f) => f.dirty),
    [draft],
  );

  const setField = useCallback(<K extends keyof DraftState>(
    key: K,
    value: DraftState[K]["value"],
  ) => {
    setDraft((d) => ({ ...d, [key]: { value, dirty: true } } as DraftState));
  }, []);

  const buildPatch = useCallback((): OverrideUpdate => {
    const out: OverrideUpdate = {};
    if (draft.display_name.dirty) out.display_name = nullIfEmpty(draft.display_name.value);
    if (draft.sort_title.dirty) out.sort_title = nullIfEmpty(draft.sort_title.value);
    if (draft.tagline.dirty) out.tagline = nullIfEmpty(draft.tagline.value);
    if (draft.year.dirty) out.year = draft.year.value;
    if (draft.runtime_min.dirty) out.runtime_min = draft.runtime_min.value;
    if (draft.rating.dirty) out.rating = draft.rating.value;
    return out;
  }, [draft]);

  const handleSave = useCallback(async () => {
    if (!dirtyAny) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/admin/override/${kind}/${entityId}`, {
        method: "PATCH",
        cache: "no-store",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(buildPatch()),
      });
      if (!res.ok) {
        setError(await extractError(res));
        return;
      }
      onApplied();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }, [buildPatch, dirtyAny, entityId, kind, onApplied, onClose]);

  if (!open) return null;

  const showSaveBar = tab === "general" || tab === "details";

  return (
    <>
      <div
        className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-overrides-title"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <div className="w-full max-w-3xl rounded-lg bg-neutral-900 shadow-xl ring-1 ring-neutral-800">
          <header className="flex items-center justify-between border-b border-neutral-800 px-5 py-3">
            <h2
              id="edit-overrides-title"
              className="text-sm font-medium tracking-tight text-neutral-100"
            >
              Edit - {labelForKind(kind)}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
              aria-label="Close"
            >
              <Icon icon={X} size={16} />
            </button>
          </header>

          <div className="grid grid-cols-1 sm:grid-cols-[180px_1fr]">
            <nav
              role="tablist"
              aria-label="Edit sections"
              className="flex flex-row gap-1 overflow-x-auto border-b border-neutral-800 p-2 sm:flex-col sm:border-b-0 sm:border-r sm:p-3"
            >
              {TABS.map((t) => (
                <TabButton
                  key={t.id}
                  active={tab === t.id}
                  onClick={() => {
                    setTab(t.id);
                    setError(null);
                  }}
                  label={t.label}
                />
              ))}
            </nav>

            <div className="px-5 py-4 min-h-[280px]">
              {tab === "general" ? (
                <GeneralTab
                  draft={draft}
                  setField={setField}
                  initial={initial}
                />
              ) : tab === "details" ? (
                <DetailsTab
                  draft={draft}
                  setField={setField}
                  kind={kind}
                  initial={initial}
                />
              ) : tab === "art" ? (
                <ArtTab
                  kind={kind}
                  initial={initial}
                  onOpenArt={(role) => setArtModal({ role })}
                />
              ) : tab === "match" ? (
                <FixMatchTab
                  kind={kind}
                  entityId={entityId}
                  currentLabel={describeForMatch(initial)}
                  onApplied={onApplied}
                  onClose={onClose}
                />
              ) : (
                <RefreshTab
                  kind={kind}
                  entityId={entityId}
                  external={initial.external_id}
                  onApplied={onApplied}
                  onClose={onClose}
                />
              )}

              {error ? (
                <p
                  role="alert"
                  className="mt-3 rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-200"
                >
                  {error}
                </p>
              ) : null}
            </div>
          </div>

          {showSaveBar ? (
            <footer className="flex items-center justify-end gap-2 border-t border-neutral-800 px-5 py-3">
              <button
                type="button"
                onClick={onClose}
                className="rounded px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={busy || !dirtyAny}
                className="rounded bg-hive px-3 py-1.5 text-sm font-medium text-on-hive hover:bg-hive-hover disabled:opacity-50"
              >
                {busy ? "Saving..." : "Save changes"}
              </button>
            </footer>
          ) : null}
        </div>
      </div>

      {artModal && ART_KIND_MAP[kind] ? (
        <ArtOverrideModal
          open
          entityKind={ART_KIND_MAP[kind]!}
          entityId={entityId}
          role={artModal.role}
          title={`${labelForKind(kind)} - ${artModal.role}`}
          hasOverride={artHasOverride(initial, artModal.role)}
          onClose={() => setArtModal(null)}
          onApplied={() => {
            setArtModal(null);
            onApplied();
          }}
        />
      ) : null}
    </>
  );
}

function buildInitialDraft(initial: Props["initial"]): DraftState {
  const ov = (initial.overrides ?? {}) as Record<string, unknown>;
  return {
    display_name: { value: asString(ov.display_name), dirty: false },
    sort_title: { value: initial.sort_title, dirty: false },
    tagline: { value: asString(ov.tagline), dirty: false },
    year: { value: asNumber(ov.year), dirty: false },
    runtime_min: { value: asNumber(ov.runtime_min), dirty: false },
    rating: { value: asNumber(ov.rating), dirty: false },
  };
}

function GeneralTab({
  draft,
  setField,
  initial,
}: {
  draft: DraftState;
  setField: <K extends keyof DraftState>(k: K, v: DraftState[K]["value"]) => void;
  initial: Props["initial"];
}) {
  const canonicalName =
    (initial.canonical?.title as string | undefined) ??
    (initial.canonical?.name as string | undefined) ??
    "";
  return (
    <Section title="General">
      <Field label="Display name" hint={canonicalName ? `Default: ${canonicalName}` : undefined}>
        <input
          type="text"
          value={draft.display_name.value ?? ""}
          placeholder={canonicalName}
          onChange={(e) => setField("display_name", e.target.value)}
          className={inputClass}
        />
      </Field>
      <Field
        label="Sort title"
        hint={`Default sort: ${initial.algorithmic_sort_hint}`}
      >
        <input
          type="text"
          value={draft.sort_title.value ?? ""}
          placeholder={initial.algorithmic_sort_hint}
          onChange={(e) => setField("sort_title", e.target.value)}
          className={inputClass}
        />
      </Field>
      <Field label="Tagline">
        <input
          type="text"
          value={draft.tagline.value ?? ""}
          placeholder={(initial.canonical?.tagline as string | undefined) ?? ""}
          onChange={(e) => setField("tagline", e.target.value)}
          className={inputClass}
        />
      </Field>
    </Section>
  );
}

function DetailsTab({
  draft,
  setField,
  kind,
  initial,
}: {
  draft: DraftState;
  setField: <K extends keyof DraftState>(k: K, v: DraftState[K]["value"]) => void;
  kind: OverrideKind;
  initial: Props["initial"];
}) {
  const showRuntime = RUNTIME_KINDS.has(kind);
  return (
    <Section title="Details">
      <Field label="Year">
        <input
          type="number"
          value={draft.year.value ?? ""}
          placeholder={String(initial.canonical?.year ?? "")}
          onChange={(e) => setField("year", numberOrNull(e.target.value))}
          className={inputClass}
          min={1800}
          max={2200}
        />
      </Field>
      {showRuntime ? (
        <Field label="Runtime (minutes)">
          <input
            type="number"
            value={draft.runtime_min.value ?? ""}
            placeholder={String(initial.canonical?.runtime_min ?? "")}
            onChange={(e) => setField("runtime_min", numberOrNull(e.target.value))}
            className={inputClass}
            min={1}
            max={10000}
          />
        </Field>
      ) : null}
      <Field label="Rating">
        <input
          type="number"
          value={draft.rating.value ?? ""}
          placeholder={String(initial.canonical?.rating ?? "")}
          onChange={(e) => setField("rating", numberOrNull(e.target.value))}
          className={inputClass}
          step={0.1}
          min={0}
          max={10}
        />
      </Field>
    </Section>
  );
}

function ArtTab({
  kind,
  initial,
  onOpenArt,
}: {
  kind: OverrideKind;
  initial: Props["initial"];
  onOpenArt: (role: ArtRole) => void;
}) {
  const supported = Boolean(ART_KIND_MAP[kind]);
  if (!supported) {
    return (
      <Section title="Art">
        <p className="text-xs text-neutral-400">
          Release-level art editing is not yet wired up. Per-video thumbs
          remain editable on individual videos in a future pass.
        </p>
      </Section>
    );
  }

  const poster = (initial.canonical?.poster_path as string | undefined) ?? null;
  const backdrop = (initial.canonical?.backdrop_path as string | undefined) ?? null;
  const showBackdrop = kind === "movie" || kind === "series";
  const posterRole: ArtRole = kind === "artist" ? "thumb" : "poster";
  const posterLabel = kind === "artist" ? "Image" : "Poster";

  return (
    <Section title="Art">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <ArtCell label={posterLabel} src={poster} onEdit={() => onOpenArt(posterRole)} />
        {showBackdrop ? (
          <ArtCell label="Backdrop" src={backdrop} onEdit={() => onOpenArt("backdrop")} />
        ) : null}
      </div>
    </Section>
  );
}

function ArtCell({
  label,
  src,
  onEdit,
}: {
  label: string;
  src: string | null;
  onEdit: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div className="aspect-[2/3] w-full overflow-hidden rounded border border-neutral-800 bg-neutral-950">
        {src ? (
          <img
            src={src}
            alt={label}
            className="h-full w-full object-cover"
            loading="lazy"
            decoding="async"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-neutral-500">
            No art
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={onEdit}
        className="w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 hover:bg-neutral-700"
      >
        Edit {label.toLowerCase()}
      </button>
    </div>
  );
}

function FixMatchTab({
  kind,
  entityId,
  currentLabel,
  onApplied,
  onClose,
}: {
  kind: OverrideKind;
  entityId: string;
  currentLabel: string;
  onApplied: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState(currentLabel);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<MatchCandidate[] | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [confirming, setConfirming] = useState<MatchCandidate | null>(null);
  const [applying, setApplying] = useState(false);

  const search = useCallback(async () => {
    const term = query.trim();
    if (!term) return;
    setBusy(true);
    setError(null);
    setResults(null);
    setNotes([]);
    setConfirming(null);
    try {
      const res = await fetch(
        `/api/admin/match/${kind}/${entityId}/candidates?q=${encodeURIComponent(term)}`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        setError(await extractError(res));
        return;
      }
      const body = (await res.json()) as MatchCandidatesOut;
      setResults(Array.isArray(body.candidates) ? body.candidates : []);
      setNotes(Array.isArray(body.notes) ? body.notes : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }, [entityId, kind, query]);

  const apply = useCallback(async (candidate: MatchCandidate) => {
    setApplying(true);
    setError(null);
    try {
      const res = await fetch(`/api/admin/match/${kind}/${entityId}`, {
        method: "POST",
        cache: "no-store",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ source: candidate.source, ref: candidate.ref }),
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
      setApplying(false);
    }
  }, [entityId, kind, onApplied, onClose]);

  if (kind === "track") {
    return (
      <Section title="Fix Match">
        <p className="text-xs text-neutral-400">
          Tracks are matched implicitly through their parent album. Fix
          Match for tracks is not supported.
        </p>
      </Section>
    );
  }

  return (
    <Section title="Fix Match">
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void search();
          }}
          placeholder="Search title..."
          className={inputClass}
        />
        <button
          type="button"
          onClick={search}
          disabled={busy || !query.trim()}
          className="rounded bg-hive px-3 py-1.5 text-sm font-medium text-on-hive hover:bg-hive-hover disabled:opacity-50"
        >
          {busy ? "Searching..." : "Search"}
        </button>
      </div>

      <SourceCallouts notes={notes} />

      {results === null ? (
        <p className="mt-3 text-xs text-neutral-500">
          Type a search term and press Enter.
        </p>
      ) : results.length === 0 ? (
        <p className="mt-3 text-xs text-neutral-500">
          No candidates returned.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {results.map((c) => (
            <li
              key={`${c.source}:${c.ref}`}
              className="flex items-start gap-3 rounded border border-neutral-800 bg-neutral-950/60 p-2"
            >
              {c.image_url ? (
                <img
                  src={c.image_url}
                  alt=""
                  className="h-20 w-14 flex-none rounded object-cover"
                  loading="lazy"
                />
              ) : (
                <div className="h-20 w-14 flex-none rounded bg-neutral-900" />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm text-neutral-100">
                  {c.label}
                  {c.year ? (
                    <span className="ml-2 text-xs text-neutral-400">
                      ({c.year})
                    </span>
                  ) : null}
                </div>
                <div className="mt-0.5 flex items-center gap-2">
                  <SourceTag source={c.source} />
                  <span className="truncate text-[10px] uppercase tracking-wider text-neutral-500">
                    {c.ref}
                  </span>
                </div>
                {c.summary ? (
                  <p className="mt-1 line-clamp-2 text-xs text-neutral-400">
                    {c.summary}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => setConfirming(c)}
                disabled={applying}
                className="self-center rounded bg-neutral-800 px-3 py-1 text-xs text-neutral-100 hover:bg-neutral-700 disabled:opacity-50"
              >
                Apply
              </button>
            </li>
          ))}
        </ul>
      )}

      {confirming ? (
        <div className="mt-3 rounded border border-line bg-hive-tint p-3">
          <p className="text-xs text-ink">
            Re-match <b>{currentLabel}</b> to <b>{confirming.label}</b>?
            Existing manual overrides will not be touched; canonical
            metadata will refresh from {confirming.source}.
          </p>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirming(null)}
              className="rounded px-3 py-1 text-xs text-neutral-300 hover:bg-neutral-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => apply(confirming)}
              disabled={applying}
              className="rounded bg-hive px-3 py-1 text-xs font-medium text-on-hive hover:bg-hive-hover disabled:opacity-50"
            >
              {applying ? "Applying..." : "Confirm re-match"}
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="mt-3 rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          {error}
        </p>
      ) : null}
    </Section>
  );
}

function RefreshTab({
  kind,
  entityId,
  external,
  onApplied,
  onClose,
}: {
  kind: OverrideKind;
  entityId: string;
  external: { source: string; id: string } | null;
  onApplied: () => void;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/admin/refresh/${kind}/${entityId}`, {
        method: "POST",
        cache: "no-store",
      });
      if (!res.ok) {
        setError(await extractError(res));
        return;
      }
      onApplied();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setBusy(false);
    }
  }, [entityId, kind, onApplied, onClose]);

  return (
    <Section title="Refresh">
      {external ? (
        <>
          <p className="text-xs text-neutral-400">
            Re-pull canonical metadata from{" "}
            <span className="text-neutral-200">
              {external.source}:{external.id}
            </span>
            . Manual overrides remain in place; only canonical fields refresh.
          </p>
          <button
            type="button"
            onClick={refresh}
            disabled={busy}
            className="mt-3 rounded bg-hive px-3 py-1.5 text-sm font-medium text-on-hive hover:bg-hive-hover disabled:opacity-50"
          >
            {busy ? "Refreshing..." : `Refresh from ${external.source}:${external.id}`}
          </button>
        </>
      ) : (
        <p className="text-xs text-neutral-400">
          This entity has no external id attached; nothing to refresh.
          Use Fix Match to attach one first.
        </p>
      )}
      {error ? (
        <p className="mt-3 rounded border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          {error}
        </p>
      ) : null}
    </Section>
  );
}

// ---- helpers --------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section role="tabpanel" aria-label={title} className="space-y-3">
      {children}
    </section>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-xs text-neutral-300">{label}</label>
      {children}
      {hint ? <p className="text-[10px] text-neutral-500">{hint}</p> : null}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex-shrink-0 rounded px-3 py-1.5 text-left text-sm sm:w-full ${
        active
          ? "bg-neutral-800 text-neutral-100"
          : "text-neutral-400 hover:bg-neutral-800/60 hover:text-neutral-200"
      }`}
    >
      {label}
    </button>
  );
}

function asString(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function numberOrNull(s: string): number | null {
  const t = s.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function nullIfEmpty(s: string | null): string | null {
  if (s === null) return null;
  const t = s.trim();
  return t === "" ? null : t;
}

function labelForKind(kind: OverrideKind): string {
  switch (kind) {
    case "music_video_release":
      return "Music Video Release";
    case "movie":
      return "Movie";
    case "series":
      return "Series";
    case "artist":
      return "Artist";
    case "album":
      return "Album";
    case "track":
      return "Track";
    default:
      return kind;
  }
}

function describeForMatch(initial: Props["initial"]): string {
  return (
    (initial.canonical?.title as string | undefined) ??
    (initial.canonical?.name as string | undefined) ??
    ""
  );
}

function artHasOverride(initial: Props["initial"], role: ArtRole): boolean {
  if (role === "poster" || role === "thumb") {
    const v = initial.canonical?.poster_path as string | undefined;
    return Boolean(v && v.startsWith("/api/art/"));
  }
  if (role === "backdrop") {
    const v = initial.canonical?.backdrop_path as string | undefined;
    return Boolean(v && v.startsWith("/api/art/"));
  }
  return false;
}

async function extractError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail) && detail.length > 0) {
        return JSON.stringify(detail[0]);
      }
    }
  } catch {
    // fall through to status code
  }
  return `HTTP ${res.status}`;
}

const inputClass =
  "block w-full rounded border border-neutral-800 bg-neutral-950 px-3 py-1.5 text-sm text-neutral-100 placeholder-neutral-600 focus:border-ink focus:outline-none";

// Avoid an import-time warning when the file is bundled but no
// reference to useRef is left; the linter wants every imported symbol
// used.
void useRef;
