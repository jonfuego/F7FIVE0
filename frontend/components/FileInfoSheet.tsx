// The File info sheet, shared by TV episodes (components/EpisodeRow) and the
// movie detail page. A 3-dot menu opens a modal that lists one media file's
// rows: codec, bitrate, container, resolution, audio, size. The file path is
// shown to admins only, on its own line, left-aligned, with a copy button;
// members see the other rows but not the path.
//
// Both callers live inside a `.detail` wrapper, so the `.ep-*` and `.card`
// styles in globals.css apply here too.

"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, MoreVertical, X } from "lucide-react";
import { Icon } from "@/components/Icon";
import { fileInfoRows, type FileInfoSource } from "@/lib/file-info";

// Everything the sheet needs from a media file: the pure-helper rows plus the
// raw path (shown to admins only, with its own copy button).
type FileLike = FileInfoSource;

export function FileInfoSheet({
  file,
  label,
  isAdmin,
  onClose,
}: {
  file: FileLike;
  label: string;
  isAdmin: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Members never see the path; admins get it on its own line below.
  const rows = fileInfoRows(file).filter((r) => r.label !== "File path");

  return (
    <div className="ep-info-scrim" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`File info: ${label}`}
        className="card font-sans ep-info"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ep-info-head">
          <h4>File info</h4>
          <button type="button" aria-label="Close" onClick={onClose}>
            <Icon icon={X} size={16} />
          </button>
        </div>
        <div className="ep-info-sub">{label}</div>
        {rows.map((r) => (
          <div className="row" key={r.label}>
            <span>{r.label}</span>
            <span>{r.value}</span>
          </div>
        ))}
        {isAdmin && file.path ? <FilePathRow path={file.path} /> : null}
      </div>
    </div>
  );
}

function FilePathRow({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(path);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard denied (no permission, insecure origin): leave the path for
      // the admin to select by hand.
    }
  }

  return (
    <div className="file-path-row">
      <div className="file-path-head">
        <span>File path</span>
        <button type="button" onClick={copy} aria-label="Copy file path" className="file-path-copy">
          <Icon icon={copied ? Check : Copy} size={14} />
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <code className="file-path-value">{path}</code>
    </div>
  );
}

// The 3-dot menu button that opens the sheet. Used by EpisodeRow and the movie
// detail page so both share one menu and one sheet.
export function FileInfoMenuButton({
  file,
  label,
  isAdmin,
}: {
  file: FileLike;
  label: string;
  isAdmin: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div ref={ref} className="ep-menu">
      <button
        type="button"
        className="ep-menu-btn"
        aria-label={`${label} actions`}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((v) => !v)}
      >
        <Icon icon={MoreVertical} size={18} />
      </button>
      {menuOpen ? (
        <div role="menu" className="ep-menu-pop">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setInfoOpen(true);
            }}
          >
            File info
          </button>
        </div>
      ) : null}
      {infoOpen ? (
        <FileInfoSheet file={file} label={label} isAdmin={isAdmin} onClose={() => setInfoOpen(false)} />
      ) : null}
    </div>
  );
}

export default FileInfoSheet;
