// Title block at the top of every /admin/<area> page.

import type { ReactNode } from "react";

export function AdminPageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-5">
      <h1 className="title-1 text-ink">{title}</h1>
      {children ? <p className="body mt-1 max-w-2xl text-ink-2">{children}</p> : null}
    </header>
  );
}
