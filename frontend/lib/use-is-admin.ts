// Is the signed-in user an admin? Used to gate admin-only detail on member
// pages (for example the file path in the File info sheet). Reads
// /api/session/me through the shared authed client, which refreshes an expired
// access token once. A non-admin or a failed read stays false.

"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/client-api";
import type { Me } from "@/lib/types";

export function useIsAdmin(): boolean {
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void apiGet<Me | null>("/api/session/me")
      .then((me) => {
        if (!cancelled && me?.role === "admin") setIsAdmin(true);
      })
      .catch(() => {
        // Non-admin or not signed in: stays false.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return isAdmin;
}
