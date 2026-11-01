// Back control for the detail pages: an arrow only, at the top left of the
// detail block above the poster or art. Replaces the "← Back" text buttons
// that sat in each page's CTA row. Styled by `.back-arrow` in globals.css.
// When you opened this page from a list (Movies, Music Artists / Albums /
// Songs, TV, Music Videos, Home, Search), it goes back in history to that list,
// which comes back at the scroll position you left it, like the browser's
// Back (lib/scroll-restoration.tsx). Otherwise (a direct link, a reload with no
// list behind it, deeper pages) it follows `href` and marks it to restore.

"use client";

import { useEffect } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Icon } from "@/components/Icon";
import { backToList, hookPopstate, markBackNavigation } from "@/lib/scroll-restoration";

export function BackButton({ href }: { href: string }) {
  const router = useRouter();
  // So the browser's Back from here restores the list even when this page was
  // the first one loaded in the tab.
  useEffect(() => {
    hookPopstate();
  }, []);
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    // New tab / window clicks keep the plain link.
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (backToList()) {
      e.preventDefault();
      router.back();
      return;
    }
    markBackNavigation(href);
  };
  return (
    <Link
      href={href}
      className="back-arrow"
      aria-label="Back"
      title="Back"
      onClick={onClick}
    >
      <Icon icon={ArrowLeft} size={22} />
    </Link>
  );
}
