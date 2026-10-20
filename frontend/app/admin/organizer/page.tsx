// /admin/organizer — per-library file organizer
// Rename files by naming template, write tags by profile, preview changes,
// apply or undo a run, and manage the recycle folder.

"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { apiGet, apiPut, apiPost, apiDelete, ApiError } from "@/lib/client-api";
import { inputCls, primaryButtonCls, smallButtonCls } from "../admin-ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type LibraryOut = {
  id: string;
  kind: string;
  name: string;
};

type OrganizerSettings = {
  ownership?: string;
  naming_template?: Record<string, string>;
  tag_profile?: Record<string, unknown>;
  recycle_folder?: string;
  flip_flop_warnings?: string[];
  presets?: {
    plex: Record<string, string>;
    arr: Record<string, string>;
    flat: Record<string, string>;
  };
};

type TemplatePreviewItem = {
  media_file_id: string;
  old_path: string;
  new_path: string | null;
  old_tags: Record<string, unknown> | null;
  new_tags: Record<string, unknown> | null;
};

type JournalItem = {
  id: string;
  item_kind: string;
  old_path: string;
  new_path: string | null;
  error: string | null;
  sort_order: number;
};

type Journal = {
  id: string;
  library_id: string | null;
  state: string;
  started_at: string;
  finished_at: string | null;
  item_count: number;
  error: string | null;
  undo_applied_at: string | null;
  items: JournalItem[];
};

type RecycleFile = {
  path: string;
  filename: string;
  size: number;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
}

function basename(p: string): string {
  return p.replace(/\\/g, "/").split("/").pop() ?? p;
}

const PRESET_NAMES: Record<string, string> = { plex: "Plex", arr: "*arr", flat: "Flat" };

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------
export default function OrganizerPage() {
  const [libraries, setLibraries] = useState<LibraryOut[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [settings, setSettings] = useState<OrganizerSettings | null>(null);
  const [preview, setPreview] = useState<TemplatePreviewItem[]>([]);
  const [journals, setJournals] = useState<Journal[]>([]);
  const [recycle, setRecycle] = useState<RecycleFile[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveFeedback, setSaveFeedback] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [emptyingRecycle, setEmptyingRecycle] = useState(false);

  // Draft state for the settings form
  const [draftOwnership, setDraftOwnership] = useState("");
  const [draftTemplate, setDraftTemplate] = useState<Record<string, string>>({});
  const [draftRecycleFolder, setDraftRecycleFolder] = useState("");

  const selectedLib = libraries.find((l) => l.id === selectedId);

  // Load the list of libraries
  useEffect(() => {
    apiGet<{ libraries: LibraryOut[] }>("/api/library/libraries")
      .then((r) => {
        const libs = (r.libraries ?? []).filter(
          (l) => l.kind === "movies" || l.kind === "tv" || l.kind === "music",
        );
        setLibraries(libs);
        if (libs.length > 0 && !selectedId) setSelectedId(libs[0].id);
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : "Failed to load libraries."));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadSettings = useCallback(async (libId: string) => {
    try {
      const s = await apiGet<OrganizerSettings>(
        `/api/admin/library/organizer/${libId}/settings`,
      );
      setSettings(s);
      setDraftOwnership(s.ownership ?? "f7five0");
      setDraftTemplate(s.naming_template ?? {});
      setDraftRecycleFolder(s.recycle_folder ?? ".f7five0-recycle");
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load settings.");
    }
  }, []);

  const loadPreview = useCallback(async (libId: string) => {
    try {
      const items = await apiGet<TemplatePreviewItem[]>(
        `/api/admin/library/organizer/${libId}/template-preview`,
      );
      setPreview(items);
    } catch {
      setPreview([]);
    }
  }, []);

  const loadJournals = useCallback(async (libId: string) => {
    try {
      const js = await apiGet<Journal[]>(
        `/api/admin/library/organizer/journals?library_id=${libId}&limit=5`,
      );
      setJournals(js);
    } catch {
      setJournals([]);
    }
  }, []);

  const loadRecycle = useCallback(async (libId: string) => {
    try {
      const files = await apiGet<RecycleFile[]>(
        `/api/admin/library/organizer/${libId}/recycle`,
      );
      setRecycle(files);
    } catch {
      setRecycle([]);
    }
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setLoadError(null);
    loadSettings(selectedId);
    loadPreview(selectedId);
    loadJournals(selectedId);
    loadRecycle(selectedId);
  }, [selectedId, loadSettings, loadPreview, loadJournals, loadRecycle]);

  async function handleSave() {
    if (!selectedId) return;
    setSaving(true);
    setSaveFeedback(null);
    try {
      const result = await apiPut<{ flip_flop_warnings: string[] }>(
        `/api/admin/library/organizer/${selectedId}/settings`,
        {
          ownership: draftOwnership,
          naming_template: draftTemplate,
          recycle_folder: draftRecycleFolder,
        },
      );
      setSaveFeedback(
        result.flip_flop_warnings?.length
          ? `Saved. Warning: ${result.flip_flop_warnings.join("; ")}`
          : "Saved.",
      );
      await loadSettings(selectedId);
    } catch (e) {
      setSaveFeedback(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function handlePreview() {
    if (!selectedId) return;
    setPreviewing(true);
    try {
      await apiPost(`/api/admin/library/organizer/${selectedId}/preview`, {});
      await loadJournals(selectedId);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.detail ?? e.message : e instanceof Error ? e.message : "Preview failed.");
    } finally {
      setPreviewing(false);
    }
  }

  async function handleApply(journal: Journal) {
    if (!selectedId) return;
    setApplying(true);
    try {
      await apiPost(
        `/api/admin/library/organizer/${selectedId}/apply/${journal.id}`,
        {},
      );
      await loadJournals(selectedId);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.detail ?? e.message : e instanceof Error ? e.message : "Apply failed.");
    } finally {
      setApplying(false);
    }
  }

  async function handleUndo(journal: Journal) {
    if (!selectedId) return;
    setUndoing(true);
    try {
      await apiPost(
        `/api/admin/library/organizer/${selectedId}/undo/${journal.id}`,
        {},
      );
      await loadJournals(selectedId);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.detail ?? e.message : e instanceof Error ? e.message : "Undo failed.");
    } finally {
      setUndoing(false);
    }
  }

  async function handleEmptyRecycle() {
    if (!selectedId) return;
    setEmptyingRecycle(true);
    try {
      await apiDelete(`/api/admin/library/organizer/${selectedId}/recycle`);
      setRecycle([]);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Empty recycle failed.");
    } finally {
      setEmptyingRecycle(false);
    }
  }

  function applyPreset(presetKey: string) {
    if (!settings?.presets) return;
    const preset = settings.presets[presetKey as keyof typeof settings.presets];
    if (preset) setDraftTemplate({ ...preset });
  }

  const latestJournal = journals[0] ?? null;

  return (
    <>
      <AdminPageHeader title="Organizer">
        Rename files by naming template and write audio tags per library.
      </AdminPageHeader>

      {loadError && (
        <p className="body-2 mb-4 text-hive-text">{loadError}</p>
      )}

      {libraries.length === 0 && !loadError && (
        <p className="body-2 text-ink-2">No music, movies, or TV libraries found.</p>
      )}

      {libraries.length > 1 && (
        <div className="mb-6">
          <label className="caption mb-1 block text-ink-2" htmlFor="lib-picker">
            Library
          </label>
          <select
            id="lib-picker"
            className={inputCls}
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {libraries.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} ({l.kind})
              </option>
            ))}
          </select>
        </div>
      )}

      {selectedId && settings && (
        <>
          {/* Ownership */}
          <section className="mb-6">
            <h2 className="title-3 mb-2 text-ink">Ownership</h2>
            <p className="body-2 mb-3 text-ink-2">
              Set to &ldquo;f7five0&rdquo; to let the organizer rename files. When an
              *arr app also manages this library, the organizer notifies the app after
              each run and warns about rename conflicts.
            </p>
            <div className="flex gap-4">
              {["f7five0", "arr"].map((v) => (
                <label key={v} className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    name="ownership"
                    value={v}
                    checked={draftOwnership === v}
                    onChange={() => setDraftOwnership(v)}
                  />
                  <span className="body-2 text-ink capitalize">{v === "arr" ? "*arr app" : v}</span>
                </label>
              ))}
            </div>
            {settings.flip_flop_warnings && settings.flip_flop_warnings.length > 0 && (
              <ul className="mt-2 space-y-1">
                {settings.flip_flop_warnings.map((w, i) => (
                  <li key={i} className="caption text-hive-text">{w}</li>
                ))}
              </ul>
            )}
          </section>

          {/* Naming template */}
          <section className="mb-6">
            <h2 className="title-3 mb-2 text-ink">Naming template</h2>
            <p className="body-2 mb-3 text-ink-2">
              Template tokens: <code className="caption">&#123;Title&#125;</code>,{" "}
              <code className="caption">&#123;Year&#125;</code>,{" "}
              <code className="caption">&#123;Artist&#125;</code>,{" "}
              <code className="caption">&#123;Album&#125;</code>,{" "}
              <code className="caption">&#123;Track:00&#125;</code>,{" "}
              <code className="caption">&#123;Series&#125;</code>,{" "}
              <code className="caption">&#123;Season:00&#125;</code>,{" "}
              <code className="caption">&#123;Episode:00&#125;</code>.
            </p>
            {settings.presets && (
              <div className="mb-3 flex flex-wrap gap-2">
                <span className="caption text-ink-2 self-center">Preset:</span>
                {Object.entries(PRESET_NAMES).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={smallButtonCls}
                    onClick={() => applyPreset(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {(["movie", "tv", "music"] as const).map((kind) => (
              <div key={kind} className="mb-3">
                <label className="caption mb-1 block text-ink-2 capitalize" htmlFor={`tpl-${kind}`}>
                  {kind}
                </label>
                <input
                  id={`tpl-${kind}`}
                  type="text"
                  className={inputCls}
                  value={draftTemplate[kind] ?? ""}
                  onChange={(e) => setDraftTemplate((t) => ({ ...t, [kind]: e.target.value }))}
                  placeholder={`e.g. {Title} ({Year})/{Title} ({Year})`}
                />
              </div>
            ))}
          </section>

          {/* Recycle folder */}
          <section className="mb-6">
            <h2 className="title-3 mb-2 text-ink">Recycle folder</h2>
            <p className="body-2 mb-3 text-ink-2">
              Files moved to the recycle folder instead of being permanently deleted.
            </p>
            <input
              type="text"
              className={inputCls}
              value={draftRecycleFolder}
              onChange={(e) => setDraftRecycleFolder(e.target.value)}
              placeholder=".f7five0-recycle"
            />
          </section>

          <div className="mb-8 flex items-center gap-3">
            <button
              type="button"
              className={primaryButtonCls}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? "Saving..." : "Save settings"}
            </button>
            {saveFeedback && (
              <span className="body-2 text-ink-2">{saveFeedback}</span>
            )}
          </div>

          {/* Template preview */}
          {preview.length > 0 && (
            <section className="mb-8">
              <h2 className="title-3 mb-2 text-ink">Template preview</h2>
              <p className="body-2 mb-3 text-ink-2">
                Shows how the current template would rename up to 10 files.
              </p>
              <ul className="space-y-2">
                {preview.map((item) => (
                  <li key={item.media_file_id} className="rounded-lg bg-surface-2 p-3">
                    <p className="caption truncate text-ink-2">{item.old_path}</p>
                    {item.new_path && item.new_path !== item.old_path && (
                      <p className="caption truncate font-medium text-ink">
                        &rarr; {item.new_path}
                      </p>
                    )}
                    {(!item.new_path || item.new_path === item.old_path) && (
                      <p className="caption text-ink-3">No change</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Preview / apply / undo */}
          <section className="mb-8">
            <h2 className="title-3 mb-2 text-ink">Run organizer</h2>
            <p className="body-2 mb-4 text-ink-2">
              Preview computes changes without touching any file. Apply renames
              and retags. Undo reverses the last apply.
            </p>
            <div className="mb-4 flex gap-3">
              <button
                type="button"
                className={primaryButtonCls}
                onClick={handlePreview}
                disabled={previewing || applying || undoing}
              >
                {previewing ? "Queued..." : "Preview changes"}
              </button>
              {latestJournal?.state === "preview" && (
                <button
                  type="button"
                  className={primaryButtonCls}
                  onClick={() => handleApply(latestJournal)}
                  disabled={applying || undoing}
                >
                  {applying ? "Queued..." : `Apply ${latestJournal.item_count} changes`}
                </button>
              )}
              {latestJournal?.state === "done" && (
                <button
                  type="button"
                  className={smallButtonCls}
                  onClick={() => handleUndo(latestJournal)}
                  disabled={undoing}
                >
                  {undoing ? "Queued..." : "Undo"}
                </button>
              )}
            </div>
            {journals.length > 0 && (
              <ul className="space-y-2">
                {journals.map((j) => (
                  <li key={j.id} className="rounded-lg bg-surface-2 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="body-2 font-medium text-ink capitalize">{j.state}</span>
                      <span className="caption tabular-nums text-ink-2">
                        {j.item_count} items
                      </span>
                    </div>
                    <p className="caption text-ink-3">
                      Started {new Date(j.started_at).toLocaleString()}
                    </p>
                    {j.error && (
                      <p className="caption text-hive-text">{j.error}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Recycle folder contents */}
          <section className="mb-8">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="title-3 text-ink">Recycle folder</h2>
              {recycle.length > 0 && (
                <button
                  type="button"
                  className={smallButtonCls}
                  onClick={handleEmptyRecycle}
                  disabled={emptyingRecycle}
                >
                  {emptyingRecycle ? "Emptying..." : "Empty recycle folder"}
                </button>
              )}
            </div>
            {recycle.length === 0 ? (
              <p className="body-2 text-ink-2">Recycle folder is empty.</p>
            ) : (
              <ul className="space-y-1">
                {recycle.map((f) => (
                  <li key={f.path} className="flex items-center justify-between gap-2 rounded bg-surface-2 px-3 py-2">
                    <span className="caption truncate text-ink">{basename(f.filename)}</span>
                    <span className="caption tabular-nums text-ink-2 shrink-0">
                      {fmtBytes(f.size)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </>
  );
}
