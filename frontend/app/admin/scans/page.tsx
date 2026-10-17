// /admin/scans

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { ScansSection, useScanStatuses } from "../ScansSection";

export default function ScansPage() {
  // This page is the one place that polls the scan statuses on its own.
  const { statuses, refresh } = useScanStatuses(true);
  return (
    <>
      <AdminPageHeader title="Scans">Start a scan and watch it run.</AdminPageHeader>
      <ScansSection statuses={statuses} refresh={refresh} />
    </>
  );
}
