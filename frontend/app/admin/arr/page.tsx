// /admin/arr

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { ArrSection } from "../ArrSection";

export default function ArrPage() {
  return (
    <>
      <AdminPageHeader title="Radarr, Sonarr and Lidarr">
        Connect an app and it owns that library. Leave it off and F7FIVE0 scans the folders.
      </AdminPageHeader>
      <ArrSection />
    </>
  );
}
