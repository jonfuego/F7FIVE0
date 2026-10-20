// /admin/library-health

"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { apiGet, apiDelete, ApiError } from "@/lib/client-api";
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

export default function LibraryHealthPage() {
  const [counts, setCounts] = useState<HealthCounts | null>(null);
  const [missing, setMissing] = useState<MissingFileItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Set<string>>(new Set());
  const [removeErrors, setRemoveErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [c, m] = await Promise.all([
        apiGet<HealthCounts>("/api/admin/library/health"),
        apiGet<MissingFileItem[]>("/api/admin/library/health/missing-files"),
      ]);
      setCounts(c);
      setMissing(m);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load health data.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function removeFile(id: string) {
    setRemoving((prev) => new Set(prev).add(id));
    setRemoveErrors((prev) => { const n = { ...prev }; delete n[id]; return n; });
    try {
      await apiDelete(`/api/admin/library/health/missing-files/${id}`);
      setMissing((prev) => prev.filter((f) => f.media_file_id !== id));
      load();
    } catch (err) {
      const msg =
        err instanceof ApiError && err.detail === "file_present"
          ? "File is back on disk."
          : err instanceof Error
          ? err.message
          : "Remove failed.";
      setRemoveErrors((prev) => ({ ...prev, [id]: msg }));
    } finally {
      setRemoving((prev) => { const n = new Set(prev); n.delete(id); return n; });
    }
  }

  return (
    <>
      <AdminPageHeader title="Library health">
        Missing files, probe errors, and unreachable folders.
      </AdminPageHeader>

      {loadError && (
        <p className="body-2 mb-4 text-hive-text">{loadError}</p>
      )}

      {counts && (
        <div className="mb-6 grid grid-cols-2 gap-3 min-[600px]:grid-cols-4">
          <CountCard label="Missing files" value={counts.missing_files_total} />
          <CountCard label="Eligible for cleanup" value={counts.missing_files_eligible} />
          <CountCard label="Probe errors" value={counts.probe_errors} />
          <CountCard label="Unreachable folders" value={counts.unreachable_folders} />
        </div>
      )}

      {missing.length > 0 && (
        <section aria-labelledby="missing-heading">
          <h2 id="missing-heading" className="title-3 mb-3 text-ink">
            Eligible missing files
          </h2>
          <p className="body-2 mb-4 text-ink-2">
            These files have been missing for 7 or more days and their library
            folder is reachable. Removing a file deletes the item when it was
            the last file for that item.
          </p>
          <ul className="space-y-2">
            {missing.map((f) => (
              <li
                key={f.media_file_id}
                className="flex flex-col gap-1 rounded-lg bg-surface-2 p-3 min-[600px]:flex-row min-[600px]:items-center min-[600px]:justify-between"
              >
                <div className="min-w-0">
                  {f.item_title && (
                    <p className="body-1 truncate font-medium text-ink">{f.item_title}</p>
                  )}
                  <p className="caption truncate text-ink-2">{f.path}</p>
                  <p className="caption text-ink-3">
                    Missing {f.days_missing} {f.days_missing === 1 ? "day" : "days"}
                    {f.library_kind ? ` · ${f.library_kind}` : ""}
                  </p>
                  {removeErrors[f.media_file_id] && (
                    <p className="caption text-hive-text">{removeErrors[f.media_file_id]}</p>
                  )}
                </div>
                <button
                  type="button"
                  className={smallButtonCls}
                  disabled={removing.has(f.media_file_id)}
                  onClick={() => removeFile(f.media_file_id)}
                >
                  {removing.has(f.media_file_id) ? "Removing..." : "Remove"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!loadError && counts && missing.length === 0 && (
        <p className="body-2 text-ink-2">No missing files eligible for cleanup.</p>
      )}
    </>
  );
}

function CountCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-surface-2 p-4">
      <p className="caption text-ink-2">{label}</p>
      <p className="title-2 tabular-nums text-ink">{value}</p>
    </div>
  );
}
