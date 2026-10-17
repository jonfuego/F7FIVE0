// /admin/remote-access

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { RemoteAccessSection } from "../RemoteAccessSection";

export default function RemoteAccessPage() {
  return (
    <>
      <AdminPageHeader title="Remote access">
        Reach this server away from home.
      </AdminPageHeader>
      <RemoteAccessSection />
    </>
  );
}
