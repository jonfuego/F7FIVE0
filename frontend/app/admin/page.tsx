// /admin: the overview. What needs attention, five status tiles, what is
// playing and who is signed in, recent plays and sign-ins, and a grid of the
// nine settings areas, each on its own page under /admin/<area>.
//
// The layout (layout.tsx) has already checked that the visitor is an admin.
// The data comes from components/admin/useAdminOverview.ts (one shared poll).
//
// Old links keep working: the backend's reminders point at /admin#metadata and
// /admin#library-folders, and the collapsible cards used to be anchors. A hash
// that names a section now on its own page redirects there (see
// ADMIN_HASH_MAP in lib/admin-dashboard.ts).

"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { NeedsAttention } from "@/components/admin/NeedsAttention";
import { OverviewPanels } from "@/components/admin/OverviewPanels";
import { SettingsGrid } from "@/components/admin/SettingsGrid";
import { StatusTiles } from "@/components/admin/StatusTiles";
import { useAdminOverview } from "@/components/admin/useAdminOverview";
import { adminRedirectForHash, buildAttentionItems } from "@/lib/admin-dashboard";
import { buildScanRows } from "@/lib/scans-rows";
import { scanInputs } from "./ScansSection";

export default function AdminOverviewPage() {
  const router = useRouter();

  useEffect(() => {
    const go = () => {
      const to = adminRedirectForHash(window.location.hash);
      if (to) router.replace(to);
    };
    go();
    window.addEventListener("hashchange", go);
    return () => window.removeEventListener("hashchange", go);
  }, [router]);

  const { state, now, retry } = useAdminOverview(true);

  const attention = useMemo(() => {
    const scans = state.scans.data;
    return buildAttentionItems({
      reminders: state.reminders.data,
      transcodes: state.transcodes.data,
      scanRows: scans ? buildScanRows({ ...scanInputs(scans), now }) : null,
      updates: state.updates.data,
      remote: state.remote.data,
    });
  }, [state, now]);

  return (
    <div>
      <header className="mb-5">
        <p className="overline text-ink-3">Server</p>
        <h1 className="title-1 text-ink">Admin</h1>
      </header>
      <NeedsAttention items={attention} />
      <StatusTiles state={state} now={now} retry={retry} />
      <OverviewPanels state={state} now={now} retry={retry} />
      <SettingsGrid state={state} now={now} />
    </div>
  );
}
