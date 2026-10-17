// The signed-in admin, shared by every /admin page. The layout checks the role
// once and only renders its children for an admin, so a page can read `me`
// without checking again.

"use client";

import { createContext, useContext } from "react";
import type { Me } from "@/lib/types";

export const AdminContext = createContext<{ me: Me } | null>(null);

export function useAdminMe(): Me {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdminMe must be used inside the admin layout.");
  return ctx.me;
}
