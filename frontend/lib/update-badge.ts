// The Admin link's "update available" badge. Admins only: the caller checks the
// role first, and members never reach the admin endpoint. The answer comes from
// the last stored check (GET /api/admin/updates/badge: no network, no task
// query), is cached for the browser session so page changes don't refetch, and
// is reset when Admin > Updates changes the picture.

"use client";

import type { UpdateBadge } from "@/lib/types";

const CACHE_MS = 5 * 60 * 1000;
let cached: { at: number; available: boolean } | null = null;

export async function loadUpdateBadge(): Promise<boolean> {
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.available;
  try {
    const res = await fetch("/api/admin/updates/badge", { cache: "no-store" });
    if (!res.ok) return false;
    const body = (await res.json()) as UpdateBadge;
    cached = { at: Date.now(), available: Boolean(body.update_available) };
    return cached.available;
  } catch {
    return false;
  }
}

export function resetUpdateBadge(): void {
  cached = null;
}
