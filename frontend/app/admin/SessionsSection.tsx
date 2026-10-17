// Admin > Activity: active sessions, with Revoke.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet } from "@/lib/client-api";
import type { AdminSession } from "@/lib/types";
import { formatDate, formatRelative, smallButtonCls } from "./admin-ui";

export function SessionsSection() {
  const [rows, setRows] = useState<AdminSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AdminSession[]>("/api/admin/sessions");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function revoke(id: string, label: string) {
    if (!window.confirm(`Revoke this session for ${label}? The device will have to sign in again.`)) {
      return;
    }
    try {
      await apiDelete(`/api/admin/sessions/${id}`);
      setRows((prev) => (prev ? prev.filter((s) => s.id !== id) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed.");
    }
  }

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
            No active sessions.
          </div>
        ) : (
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-ink-3">
              <tr className="border-b border-line">
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Client</th>
                <th className="px-2 py-2 font-medium">Device</th>
                <th className="px-2 py-2 font-medium">Last seen</th>
                <th className="px-2 py-2 font-medium">Expires</th>
                <th className="px-2 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b border-line last:border-b-0">
                  <td className="px-2 py-2">{s.display_name}</td>
                  <td className="px-2 py-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] ${
                        s.client_type === "pwa"
                          ? "bg-surface-3 text-positive"
                          : "bg-surface-3 text-ink-2"
                      }`}
                    >
                      {s.client_type}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-ink-2">{s.device_label ?? "-"}</td>
                  <td className="px-2 py-2 text-ink-2">
                    {s.last_seen_at ? formatRelative(s.last_seen_at) : "-"}
                  </td>
                  <td className="px-2 py-2 text-ink-2">{formatDate(s.expires_at)}</td>
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => revoke(s.id, s.display_name)}
                      className={smallButtonCls}
                    >
                      Revoke
                    </button>
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
