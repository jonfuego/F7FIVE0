// Reminder banner for admins (for example: no TMDB key yet). The server
// decides what to show (GET /api/admin/reminders): a reminder comes back a
// few days after "Later" and stops after a few showings or "Don't remind me".
// Members never call the admin endpoint: the role is checked first, and the
// result is cached for the browser session so page changes don't refetch.

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { AdminReminder, Me } from "@/lib/types";

let cached: { at: number; items: AdminReminder[] } | null = null;
const CACHE_MS = 5 * 60 * 1000;

async function loadReminders(): Promise<AdminReminder[]> {
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.items;
  const meRes = await fetch("/api/session/me", { cache: "no-store" });
  if (!meRes.ok) return [];
  const me = (await meRes.json()) as Me | null;
  let items: AdminReminder[] = [];
  if (me?.role === "admin") {
    const res = await fetch("/api/admin/reminders", { cache: "no-store" });
    if (res.ok) items = (await res.json()) as AdminReminder[];
  }
  cached = { at: Date.now(), items };
  return items;
}

export function AdminReminders() {
  const [items, setItems] = useState<AdminReminder[]>([]);

  useEffect(() => {
    let cancelled = false;
    loadReminders()
      .then((r) => {
        if (!cancelled) setItems(r);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (items.length === 0) return null;
  const r = items[0];

  function snooze(forever: boolean) {
    const rest = items.filter((x) => x.id !== r.id);
    setItems(rest);
    if (cached) cached = { ...cached, items: rest };
    void fetch(`/api/admin/reminders/${encodeURIComponent(r.id)}/snooze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ forever }),
    }).catch(() => {});
  }

  return (
    <div
      role="status"
      className="mx-auto mt-4 flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-4 py-3 text-sm"
      style={{ borderColor: "var(--hive)", background: "var(--hive-tint)", color: "var(--ink)" }}
    >
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{r.title}</p>
        <p className="mt-0.5 text-xs" style={{ color: "var(--ink-2)" }}>
          {r.body}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Link
          href={r.action_href}
          onClick={() => snooze(false)}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: "var(--hive)", color: "var(--on-hive)" }}
        >
          {r.action_label}
        </Link>
        <button
          type="button"
          onClick={() => snooze(false)}
          className="rounded-md px-2.5 py-1.5 text-xs"
          style={{ color: "var(--ink-2)" }}
        >
          Later
        </button>
        <button
          type="button"
          onClick={() => snooze(true)}
          className="rounded-md px-2.5 py-1.5 text-xs"
          style={{ color: "var(--ink-3)" }}
        >
          Don&apos;t remind me
        </button>
      </div>
    </div>
  );
}
