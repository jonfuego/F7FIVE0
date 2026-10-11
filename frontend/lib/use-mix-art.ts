// Loads which mixes carry an admin-set picture, and whether the viewer is an
// admin (only admins get the edit control). Best-effort: on any failure the
// cards show the static defaults and no edit control.

"use client";

import { useCallback, useEffect, useState } from "react";
import type { MixArtMap } from "./mix-art";

export function useMixArt(): { overrides: MixArtMap; isAdmin: boolean; reload: () => void } {
  const [overrides, setOverrides] = useState<MixArtMap>({});
  const [isAdmin, setIsAdmin] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/art/mixes", { cache: "no-store" });
        if (!res.ok) return;
        const body = (await res.json()) as MixArtMap;
        if (!cancelled && body && typeof body === "object") setOverrides(body);
      } catch {
        // defaults stay
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tick]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/session/me", { cache: "no-store" });
        if (!res.ok) return;
        const me = (await res.json()) as { role?: string };
        if (!cancelled && me?.role === "admin") setIsAdmin(true);
      } catch {
        // not admin
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { overrides, isAdmin, reload };
}
