// /admin/library-folders

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LibraryFoldersSection } from "../LibraryFoldersSection";

export default function LibraryFoldersPage() {
  return (
    <>
      <AdminPageHeader title="Library folders">
        Choose where each library lives, and sign in to a NAS the server can&apos;t open on its own.
      </AdminPageHeader>
      <LibraryFoldersSection />
    </>
  );
}
