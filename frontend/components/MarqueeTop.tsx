// Sticky theatre header for the F7FIVE0 re-skin. Three columns: wordmark
// left, primary nav center, search input + user actions right. Active
// nav item gets a 2px accent underline via ::after rule in globals.css.
//
// Keyboard:
//   - "/" or Cmd/Ctrl+K from anywhere focuses the inline search input.
//   - Enter submits the query and navigates to /search?q=<value>.
//   - When already on /search, the input stays in sync with the URL's
//     ?q=, so deep-links land with the input pre-filled.
//
// The form is split into TopSearchForm and wrapped in <Suspense> so the
// useSearchParams() call doesn't force every authenticated page into
// CSR-bailout during static generation.

"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { GearMenu } from "./GearMenu";
import { Wordmark } from "./Wordmark";

type NavLink = { label: string; href: string };

const NAV: NavLink[] = [
  { label: "Home", href: "/" },
  { label: "Movies", href: "/movies" },
  { label: "TV", href: "/series" },
  { label: "Music", href: "/music" },
  { label: "Videos", href: "/music-videos" },
  { label: "Mixes", href: "/mixes" },
];

export function MarqueeTop() {
  const pathname = usePathname() ?? "/";

  return (
    <header className="marquee-top">
      <div className="marquee-row">
        <Wordmark />
        <nav className="marquee-nav" aria-label="Primary">
          {NAV.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={isActive(pathname, link.href) ? "active" : ""}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="marquee-actions">
          <Suspense fallback={<TopSearchFallback />}>
            <TopSearchForm />
          </Suspense>
          <GearMenu />
        </div>
      </div>
      <nav className="marquee-mobile-nav" aria-label="Primary mobile">
        {NAV.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={isActive(pathname, link.href) ? "active" : ""}
          >
            {link.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}

// Tiny non-interactive placeholder rendered during the suspense window
// so the layout doesn't shift while useSearchParams hydrates.
function TopSearchFallback() {
  return (
    <div className="marquee-search" aria-hidden>
      <span aria-hidden>⌕</span>
      <input
        type="search"
        placeholder="Search F7FIVE0…"
        disabled
        aria-hidden
        tabIndex={-1}
      />
    </div>
  );
}

function TopSearchForm() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const searchParams = useSearchParams();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const qParam = searchParams?.get("q") ?? "";
  const [value, setValue] = useState(qParam);
  useEffect(() => {
    if (pathname === "/search") setValue(qParam);
    else setValue("");
  }, [pathname, qParam]);

  useEffect(() => {
    function focusInput(e: KeyboardEvent) {
      e.preventDefault();
      const el = inputRef.current;
      if (el) {
        el.focus();
        el.select();
      }
    }
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        focusInput(e);
        return;
      }
      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const active = document.activeElement as HTMLElement | null;
        if (active) {
          const tag = active.tagName.toLowerCase();
          if (tag === "input" || tag === "textarea" || tag === "select") return;
          if (active.isContentEditable) return;
        }
        focusInput(e);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
    inputRef.current?.blur();
  }

  return (
    <form
      className="marquee-search"
      role="search"
      onSubmit={onSubmit}
      aria-label="Search F7FIVE0"
    >
      <span aria-hidden>⌕</span>
      <input
        ref={inputRef}
        type="search"
        name="q"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search F7FIVE0…"
        aria-label="Search F7FIVE0"
        autoComplete="off"
        spellCheck={false}
        enterKeyHint="search"
      />
    </form>
  );
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
