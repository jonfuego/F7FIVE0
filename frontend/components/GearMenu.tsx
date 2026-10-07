// Single gear-icon dropdown that replaces the trio of top-right header
// controls (UserBadge + AdminNavLink + Sign out). Same component on
// desktop and the mobile bottom nav.
//
// Menu: name + role header (non-clickable), Account link, Admin link
// (admins only), Sign out button. Sign out POSTs to /api/session/logout
// and bounces to /login. Click outside or Esc closes the panel.
//
// Admins also see a badge on the Admin link (and a dot on the gear) when the
// last update check found a newer F7FIVE0 (Admin > Updates).

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Settings } from "lucide-react";
import { Icon } from "@/components/Icon";
import { refreshSession } from "@/lib/client-api";
import { loadUpdateBadge } from "@/lib/update-badge";

type Me = {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "member" | string;
};

export function GearMenu() {
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  // Only offer the Android app when this server has one to hand out.
  const [hasApp, setHasApp] = useState(false);
  // Admins only: a newer F7FIVE0 is waiting (from the last stored check).
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const profile = await loadMeWithRefresh();
      if (!cancelled) setMe(profile);
      if (!profile) return;
      if (profile.role === "admin") {
        const waiting = await loadUpdateBadge();
        if (!cancelled) setUpdateAvailable(waiting);
      }
      try {
        const res = await fetch("/download/android", { method: "HEAD", cache: "no-store" });
        if (!cancelled) setHasApp(res.ok);
      } catch {
        // Leave the link hidden.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const node = wrapRef.current;
      if (!node) return;
      if (!node.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("mousedown", onDocClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function signOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST" });
    } finally {
      window.location.replace("/login");
    }
  }

  const roleLabel = me?.role === "admin" ? "Admin" : "Member";
  const isAdmin = me?.role === "admin";
  const showUpdate = isAdmin && updateAvailable;

  return (
    <div className="gear-menu" ref={wrapRef}>
      <button
        type="button"
        className="gear-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-label={showUpdate ? "Account menu (update available)" : "Account menu"}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <GearIcon />
        {showUpdate ? <span className="update-dot" aria-hidden="true" /> : null}
      </button>
      {open ? (
        <div className="gear-panel" role="menu">
          <div className="gear-header" aria-hidden={false}>
            <div className="gear-name">{me?.display_name ?? "—"}</div>
            <div className="gear-role">{me ? roleLabel : ""}</div>
          </div>
          <Link
            href="/account"
            className="gear-item"
            role="menuitem"
            onClick={() => setOpen(false)}
          >
            Account
          </Link>
          {hasApp ? (
            <a
              href="/download/android"
              className="gear-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              Get the Android app
            </a>
          ) : null}
          {isAdmin ? (
            <Link
              href="/admin"
              className="gear-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              Admin
              {showUpdate ? (
                <span className="update-badge" role="status" aria-label="Update available">
                  Update
                </span>
              ) : null}
            </Link>
          ) : null}
          <button
            type="button"
            className="gear-item gear-signout"
            role="menuitem"
            onClick={signOut}
            disabled={signingOut}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function GearIcon() {
  return <Icon icon={Settings} size={18} />;
}

async function loadMeWithRefresh(): Promise<Me | null> {
  const first = await fetch("/api/session/me", { cache: "no-store" });
  if (first.ok) return (await first.json()) as Me;
  if (first.status !== 401) return null;
  // Share the single-flight refresh so this does not race the data fetches.
  const refreshed = await refreshSession();
  if (!refreshed) return null;
  const retry = await fetch("/api/session/me", { cache: "no-store" });
  if (!retry.ok) return null;
  return (await retry.json()) as Me;
}
