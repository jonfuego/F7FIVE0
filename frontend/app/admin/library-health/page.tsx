// /admin/library-health
//
// Four count tiles (missing files, eligible for cleanup, probe errors,
// unreachable folders). Each tile opens its own list below it, and the URL
// carries the open list as ?view= (lib/library-health-view.ts), so a Needs
// attention link or a Scans row lands on the list it talks about.

"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { apiGet, apiDelete, ApiError } from "@/lib/client-api";
import {
  HEALTH_EMPTY_TEXT, HEALTH_PAGE_SIZE, HEALTH_VIEWS, HEALTH_VIEW_LABEL, healthTileCount,
  healthViewFromSearch, healthViewHref, type HealthView,
} from "@/lib/library-health-view";
import { smallButtonCls } from "../admin-ui";

type HealthCounts = {
  missing_files_total: number;
  missing_files_eligible: number;
  probe_errors: number;
  unreachable_folders: number;
  unmatched: Record<string, number>;
  missing_art: Record<string, number>;
};

type MissingFileItem = {
  media_file_id: string;
  path: string;
  item_title: string | null;
  library_kind: string | null;
  days_missing: number;
};

type HealthFileItem = {
  media_file_id: string;
  path: string;
  item_title: string | null;
  library_kind: string | null;
  kind: string;
  state: string;
  days_missing: number | null;
  eligible: boolean;
};

type HealthFilesPage = { total: number; items: HealthFileItem[] };

type UnreachableFolder = { path: string; library_kind: string };

const LIST_DESCRIPTION: Record<HealthView, string> = {
  missing: "Every file the last scan could not find on disk, longest missing first.",
  eligible:
    "Missing for 7 or more days while their library folder is reachable. Removing a file deletes the item when it was the last file for that item.",
  errors: "Files on disk that ffprobe could not read: damaged, incomplete, or not a media file. Fix or replace the file, then scan again.",
  unreachable: "Library folders the F7FIVE0 service cannot open right now. Their files keep their state until the folder is back.",
};

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export default function LibraryHealthPage() {
  const [counts, setCounts] = useState<HealthCounts | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Read from the URL after mount, so the page needs no Suspense boundary.
  const [view, setView] = useState<HealthView | null>(null);

  const loadCounts = useCallback(async () => {
    try {
      setCounts(await apiGet<HealthCounts>("/api/admin/library/health"));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err, "Failed to load health data."));
    }
  }, []);

  useEffect(() => {
    setView(healthViewFromSearch(window.location.search));
    void loadCounts();
  }, [loadCounts]);

  function choose(next: HealthView) {
    setView(next);
    window.history.replaceState(null, "", healthViewHref(next));
  }

  return (
    <>
      <AdminPageHeader title="Library health">
        Missing files, probe errors, and unreachable folders. Pick a count to see the list behind it.
      </AdminPageHeader>

      {loadError && <p className="body-2 mb-4 text-hive-text">{loadError}</p>}

      {counts && (
        <div role="tablist" aria-label="Library health lists" className="mb-6 grid grid-cols-2 gap-3 min-[600px]:grid-cols-4">
          {HEALTH_VIEWS.map((v) => (
            <CountTile
              key={v}
              label={HEALTH_VIEW_LABEL[v]}
              value={healthTileCount(v, counts)}
              selected={view === v}
              onSelect={() => choose(v)}
              controls={`health-list-${v}`}
            />
          ))}
        </div>
      )}

      {view ? (
        <section
          id={`health-list-${view}`}
          role="tabpanel"
          aria-labelledby={`health-heading-${view}`}
          data-testid={`health-list-${view}`}
        >
          <h2 id={`health-heading-${view}`} className="title-3 mb-1 text-ink">
            {HEALTH_VIEW_LABEL[view]}
          </h2>
          <p className="body-2 mb-4 max-w-2xl text-ink-2">{LIST_DESCRIPTION[view]}</p>
          {view === "eligible" ? (
            <EligibleList onChanged={loadCounts} />
          ) : view === "unreachable" ? (
            <UnreachableList />
          ) : (
            <FileList key={view} state={view === "missing" ? "missing" : "error"} onChanged={loadCounts} />
          )}
        </section>
      ) : null}
    </>
  );
}

function CountTile({
  label, value, selected, onSelect, controls,
}: {
  label: string;
  value: number;
  selected: boolean;
  onSelect: () => void;
  controls: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      aria-controls={controls}
      onClick={onSelect}
      className={`min-h-tap border p-4 text-left transition hover:border-ink-3 ${
        selected ? "border-ink-2 bg-surface-3" : "border-transparent bg-surface-2"
      }`}
    >
      <span className="caption block text-ink-2">{label}</span>
      <span className="title-2 block tabular-nums text-ink">{value.toLocaleString("en-US")}</span>
    </button>
  );
}

function useRemove(onRemoved: (id: string) => void) {
  const [removing, setRemoving] = useState<Set<string>>(new Set());
  const [removeErrors, setRemoveErrors] = useState<Record<string, string>>({});

  async function removeFile(id: string) {
    setRemoving((prev) => new Set(prev).add(id));
    setRemoveErrors((prev) => { const n = { ...prev }; delete n[id]; return n; });
    try {
      await apiDelete(`/api/admin/library/health/missing-files/${id}`);
      onRemoved(id);
    } catch (err) {
      const msg =
        err instanceof ApiError && err.detail === "file_present"
          ? "File is back on disk."
          : errorText(err, "Remove failed.");
      setRemoveErrors((prev) => ({ ...prev, [id]: msg }));
    } finally {
      setRemoving((prev) => { const n = new Set(prev); n.delete(id); return n; });
    }
  }

  return { removing, removeErrors, removeFile };
}

function FileRow({
  path, title, meta, error, action,
}: {
  path: string;
  title: string | null;
  meta: string;
  error?: string;
  action?: ReactNode;
}) {
  return (
    <li className="flex flex-col gap-1 border border-line bg-surface-1 p-3 min-[600px]:flex-row min-[600px]:items-center min-[600px]:justify-between">
      <div className="min-w-0">
        {title && <p className="body-1 truncate font-medium text-ink">{title}</p>}
        <p className="caption break-all text-ink-2">{path}</p>
        {meta ? <p className="caption tabular-nums text-ink-3">{meta}</p> : null}
        {error ? <p className="caption text-hive-text">{error}</p> : null}
      </div>
      {action}
    </li>
  );
}

function daysText(days: number | null): string {
  if (days === null) return "";
  return `Missing ${days} ${days === 1 ? "day" : "days"}`;
}

function EligibleList({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<MissingFileItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { removing, removeErrors, removeFile } = useRemove((id) => {
    setItems((prev) => (prev ?? []).filter((f) => f.media_file_id !== id));
    onChanged();
  });

  useEffect(() => {
    apiGet<MissingFileItem[]>("/api/admin/library/health/missing-files")
      .then(setItems)
      .catch((err) => setError(errorText(err, "Failed to load the list.")));
  }, []);

  if (error) return <p className="body-2 text-hive-text">{error}</p>;
  if (items === null) return <div className="h-16 animate-pulse bg-surface-2" />;
  if (items.length === 0) return <p className="body-2 text-ink-2">{HEALTH_EMPTY_TEXT.eligible}</p>;
  return (
    <ul className="space-y-2">
      {items.map((f) => (
        <FileRow
          key={f.media_file_id}
          path={f.path}
          title={f.item_title}
          meta={`${daysText(f.days_missing)}${f.library_kind ? ` · ${f.library_kind}` : ""}`}
          error={removeErrors[f.media_file_id]}
          action={
            <button
              type="button"
              className={smallButtonCls}
              disabled={removing.has(f.media_file_id)}
              onClick={() => void removeFile(f.media_file_id)}
            >
              {removing.has(f.media_file_id) ? "Removing..." : "Remove"}
            </button>
          }
        />
      ))}
    </ul>
  );
}

function FileList({ state, onChanged }: { state: "missing" | "error"; onChanged: () => void }) {
  const [items, setItems] = useState<HealthFileItem[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { removing, removeErrors, removeFile } = useRemove((id) => {
    setItems((prev) => prev.filter((f) => f.media_file_id !== id));
    setTotal((t) => (t === null ? t : Math.max(0, t - 1)));
    onChanged();
  });

  const loadPage = useCallback(async (offset: number) => {
    setLoading(true);
    try {
      const page = await apiGet<HealthFilesPage>(
        `/api/admin/library/health/files?state=${state}&limit=${HEALTH_PAGE_SIZE}&offset=${offset}`,
      );
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setError(errorText(err, "Failed to load the list."));
    } finally {
      setLoading(false);
    }
  }, [state]);

  useEffect(() => {
    void loadPage(0);
  }, [loadPage]);

  const view: HealthView = state === "missing" ? "missing" : "errors";
  if (error) return <p className="body-2 text-hive-text">{error}</p>;
  if (total === null) return <div className="h-16 animate-pulse bg-surface-2" />;
  if (total === 0) return <p className="body-2 text-ink-2">{HEALTH_EMPTY_TEXT[view]}</p>;
  return (
    <>
      <p className="caption mb-2 tabular-nums text-ink-3">
        Showing {items.length.toLocaleString("en-US")} of {total.toLocaleString("en-US")}
      </p>
      <ul className="space-y-2">
        {items.map((f) => {
          const kind = f.library_kind ?? f.kind;
          const meta = state === "missing"
            ? `${daysText(f.days_missing)} · ${kind}${f.eligible ? " · eligible for cleanup" : ""}`
            : kind;
          return (
            <FileRow
              key={f.media_file_id}
              path={f.path}
              title={f.item_title}
              meta={meta}
              error={removeErrors[f.media_file_id]}
              action={
                f.eligible ? (
                  <button
                    type="button"
                    className={smallButtonCls}
                    disabled={removing.has(f.media_file_id)}
                    onClick={() => void removeFile(f.media_file_id)}
                  >
                    {removing.has(f.media_file_id) ? "Removing..." : "Remove"}
                  </button>
                ) : undefined
              }
            />
          );
        })}
      </ul>
      {items.length < total ? (
        <button
          type="button"
          className={`${smallButtonCls} mt-3 min-h-tap`}
          disabled={loading}
          onClick={() => void loadPage(items.length)}
        >
          {loading ? "Loading..." : `Show ${Math.min(HEALTH_PAGE_SIZE, total - items.length)} more`}
        </button>
      ) : null}
    </>
  );
}

function UnreachableList() {
  const [items, setItems] = useState<UnreachableFolder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<UnreachableFolder[]>("/api/admin/library/health/unreachable-folders")
      .then(setItems)
      .catch((err) => setError(errorText(err, "Failed to load the list.")));
  }, []);

  if (error) return <p className="body-2 text-hive-text">{error}</p>;
  if (items === null) return <div className="h-16 animate-pulse bg-surface-2" />;
  if (items.length === 0) return <p className="body-2 text-ink-2">{HEALTH_EMPTY_TEXT.unreachable}</p>;
  return (
    <>
      <ul className="space-y-2">
        {items.map((f) => (
          <FileRow key={f.path} path={f.path} title={null} meta={f.library_kind} />
        ))}
      </ul>
      <p className="body-2 mt-3 text-ink-2">
        A network share needs a Windows sign-in for its server, and a drive letter needs a path mapping.{" "}
        <Link href="/admin/library-folders" className="font-semibold text-hive-text hover:underline">
          Open Library folders
        </Link>
      </p>
    </>
  );
}
