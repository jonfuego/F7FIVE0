// /admin/metadata

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { MetadataSection } from "../MetadataSection";

export default function MetadataPage() {
  return (
    <>
      <AdminPageHeader title="Metadata">
        The TMDB key supplies posters and details. A Podcast Index key adds podcast search.
      </AdminPageHeader>
      <MetadataSection />
    </>
  );
}
