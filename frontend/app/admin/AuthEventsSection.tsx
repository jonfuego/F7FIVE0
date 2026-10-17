// Admin > Activity: recent auth events.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/client-api";
import type { AuthEvent } from "@/lib/types";
import { formatRelative } from "./admin-ui";

export function AuthEventsSection() {
  const [rows, setRows] = useState<AuthEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AuthEvent[]>("/api/admin/auth-events?limit=50");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load auth events.");
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
            No auth events recorded.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-ink-3">
              <tr className="border-b border-line">
                <th className="px-2 py-2 font-medium">When</th>
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Event</th>
                <th className="px-2 py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="border-b border-line last:border-b-0">
                  <td className="px-2 py-2 text-ink-2">{formatRelative(e.at)}</td>
                  <td className="px-2 py-2">{e.username ?? <span className="text-ink-3">unknown</span>}</td>
                  <td className="px-2 py-2 text-ink">{e.event}</td>
                  <td className="px-2 py-2 font-sans text-xs text-ink-2">{e.ip ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
