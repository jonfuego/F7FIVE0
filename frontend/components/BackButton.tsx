// Back control for the detail pages: an arrow only, at the top left of the
// detail block above the poster or art. Replaces the "← Back" text buttons
// that sat in each page's CTA row. Styled by `.back-arrow` in globals.css.
// It marks the page it goes to so that page comes back at the scroll position
// you left it (lib/scroll-restoration.tsx), like the browser's Back.

"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Icon } from "@/components/Icon";
import { markBackNavigation } from "@/lib/scroll-restoration";

export function BackButton({ href }: { href: string }) {
  return (
    <Link
      href={href}
      className="back-arrow"
      aria-label="Back"
      title="Back"
      onClick={() => markBackNavigation(href)}
    >
      <Icon icon={ArrowLeft} size={22} />
    </Link>
  );
}
