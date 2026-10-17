// /admin/users

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { useAdminMe } from "@/components/admin/AdminContext";
import { UsersSection } from "../UsersSection";

export default function UsersPage() {
  const me = useAdminMe();
  return (
    <>
      <AdminPageHeader title="Users">
        Add people, change roles, disable accounts and reset passwords.
      </AdminPageHeader>
      <UsersSection me={me} />
    </>
  );
}
