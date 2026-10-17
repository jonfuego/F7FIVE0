// /admin/updates

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { UpdatesSection } from "../UpdatesSection";

export default function UpdatesPage() {
  return (
    <>
      <AdminPageHeader title="Updates">
        Check for a new release and update the server.
      </AdminPageHeader>
      <UpdatesSection />
    </>
  );
}
