// Shared frame for every /admin page. It checks the signed-in user's role once
// (members get the friendly "limited to administrators" message; the backend
// enforces the same rule on every call), wraps the page in AuthShell and, on
// the /admin/<area> subpages, adds the section list. The overview (/admin) has
// no list. All traffic goes through the Next BFF at /api/admin/*, which
// attaches the Bearer from the httpOnly cookie.
//
// loadMe goes through apiGet (single-flight refresh + retry), so the page
// renders on first navigation even right after the 15-min access token
// expired. See lib/load-me.ts for the cause this fixes.

"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { AuthShell } from "@/components/AuthShell";
import { Icon } from "@/components/Icon";
import { AdminContext } from "@/components/admin/AdminContext";
import { ADMIN_AREAS, ADMIN_HOME, currentAreaId } from "@/lib/admin-dashboard";
import { apiGet } from "@/lib/client-api";
import { loadMe } from "@/lib/load-me";
import type { Me } from "@/lib/types";

// The section list on every /admin/<area> page: "Overview" (back arrow) first,
// then the nine areas. The current one carries aria-current="page" and the HIVE
// mark. Wide screens put it on the left; under about 720 px it stacks above the
// content and wraps. The overview itself has no list.
const itemCls =
  "relative flex min-h-tap items-center gap-2 px-3 text-sm font-semibold text-ink-2 hover:bg-surface-2 hover:text-ink";

function AdminSectionList() {
  const current = currentAreaId(usePathname());
  return (
    <nav aria-label="Admin sections" data-testid="admin-section-list">
      <ul className="flex flex-wrap gap-1 min-[720px]:flex-col">
        <li>
          <Link href={ADMIN_HOME} className={itemCls}>
            <Icon icon={ArrowLeft} size={16} />
            Overview
          </Link>
        </li>
        {ADMIN_AREAS.map((area) => {
          const active = area.id === current;
          return (
            <li key={area.id}>
              <Link
                href={area.href}
                aria-current={active ? "page" : undefined}
                className={`${itemCls} ${active ? "text-ink" : ""}`}
                style={active ? { background: "var(--hive-tint)" } : undefined}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 w-[3px]"
                    style={{ background: "var(--hive-mark)" }}
                  />
                ) : null}
                {area.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadError(null);
    try {
      const profile = await loadMe(apiGet, signal);
      if (!profile) return;
      setMe(profile);
      if (profile.role !== "admin") setForbidden(true);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setLoadError(err instanceof Error ? err.message : "Could not load the admin page.");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (forbidden) {
    return (
      <AuthShell>
        <div className="mx-auto max-w-lg px-4 py-6 text-center">
          <h1 className="title-1 text-ink">Admin</h1>
          <p className="body mt-4 text-ink-2">This area is limited to administrators.</p>
        </div>
      </AuthShell>
    );
  }

  const onOverview = pathname === "/admin" || pathname === "/admin/";

  return (
    <AuthShell>
      <div className="mx-auto w-full max-w-[1240px] px-4 py-6 md:px-6">
        {me ? (
          <AdminContext.Provider value={{ me }}>
            {onOverview ? (
              children
            ) : (
              <div className="grid grid-cols-1 gap-5 min-[720px]:grid-cols-[220px_minmax(0,1fr)]">
                <AdminSectionList />
                <div className="min-w-0">{children}</div>
              </div>
            )}
          </AdminContext.Provider>
        ) : loadError ? (
          <div role="alert" className="border border-line bg-hive-tint px-4 py-5 text-sm text-hive-text">
            <p>{loadError}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-3 min-h-tap border border-line-strong px-3 text-xs font-semibold text-ink hover:border-ink-2"
            >
              Try again
            </button>
          </div>
        ) : (
          <div className="h-32 animate-pulse bg-surface-2" />
        )}
      </div>
    </AuthShell>
  );
}
