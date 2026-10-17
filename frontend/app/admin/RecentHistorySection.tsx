// Admin > Activity: recent watch history.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/client-api";
import { formatPosition } from "@/lib/admin-dashboard";
import type { WatchHistoryRow } from "@/lib/types";
import { formatRelative } from "./admin-ui";

export function RecentHistorySection() {
  const [rows, setRows] = useState<WatchHistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<WatchHistoryRow[]>("/api/admin/history/recent?limit=25");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div className="flex items-baseline justify-end gap-3">
        <button
          type="button"
          onClick={load}
          className="text-xs text-ink-3 hover:text-ink"
        >
          Refresh
        </button>
      </div>
      <div className="mt-4 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-line bg-hive-tint px-4 py-3 text-sm text-hive-text">
            {error}
          </div>
        ) : rows === null ? (
          <div className="h-16 animate-pulse rounded-md bg-surface-2" />
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed border-line bg-surface-2 px-4 py-6 text-sm text-ink-3">
            Nothing played yet.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-ink-3">
              <tr className="border-b border-line">
                <th className="px-2 py-2 font-medium">When</th>
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Title</th>
                <th className="px-2 py-2 font-medium text-right">Position</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-b-0">
                  <td className="px-2 py-2 text-ink-2">
                    {formatRelative(r.started_at)}
                  </td>
                  <td className="px-2 py-2">{r.user_display_name}</td>
                  <td className="px-2 py-2 text-ink">{r.title}</td>
                  <td className="px-2 py-2 text-right font-sans text-xs text-ink-2">
                    {formatPosition(r.last_position_sec)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
