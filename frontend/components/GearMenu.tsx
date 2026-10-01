// Single gear-icon dropdown that replaces the trio of top-right header
// controls (UserBadge + AdminNavLink + Sign out). Same component on
// desktop and the mobile bottom nav.
//
// Menu: name + role header (non-clickable), Account link, Admin link
// (admins only), Sign out button. Sign out POSTs to /api/session/logout
// and bounces to /login. Click outside or Esc closes the panel.

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const profile = await loadMeWithRefresh();
      if (!cancelled) setMe(profile);
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

  return (
    <div className="gear-menu" ref={wrapRef}>
      <button
        type="button"
        className="gear-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <GearIcon />
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
          <a
            href="/download/android"
            className="gear-item"
            role="menuitem"
            onClick={() => setOpen(false)}
          >
            Get the Android app
          </a>
          {isAdmin ? (
            <Link
              href="/admin"
              className="gear-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              Admin
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
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

async function loadMeWithRefresh(): Promise<Me | null> {
  const first = await fetch("/api/session/me", { cache: "no-store" });
  if (first.ok) return (await first.json()) as Me;
  if (first.status !== 401) return null;
  const refresh = await fetch("/api/session/refresh", { method: "POST" });
  if (!refresh.ok) return null;
  const retry = await fetch("/api/session/me", { cache: "no-store" });
  if (!retry.ok) return null;
  return (await retry.json()) as Me;
}
