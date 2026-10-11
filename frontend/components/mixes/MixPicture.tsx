// The picture slot of a mix card: default SVG or the admin's override, plus
// (admins only) an Edit button that opens the shared art modal. The modal's
// "Reset to default" removes the override.

"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import { ArtOverrideModal } from "@/components/ArtOverrideModal";
import { artSized } from "@/lib/art-url";
import { mixArtSrc, type MixArtMap } from "@/lib/mix-art";

export function MixPicture({
  mixKey,
  title,
  overrides,
  isAdmin,
  onChanged,
}: {
  mixKey: string;
  title: string;
  overrides: MixArtMap;
  isAdmin: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const raw = mixArtSrc(mixKey, overrides);
  if (!raw) return null;
  const src = artSized(raw, 600) ?? raw;
  return (
    <>
      <img src={src} alt="" className="pb-img" loading="lazy" decoding="async" />
      {isAdmin ? (
        <>
          <button
            type="button"
            className="admin-edit"
            aria-label={`Edit picture for ${title}`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setEditing(true);
            }}
          >
            Edit
          </button>
          {/* Portaled: a hovered playbill is transformed, which would make a
              fixed modal position against the card instead of the screen. */}
          {editing
            ? createPortal(
                <ArtOverrideModal
                  open
                  onClose={() => setEditing(false)}
                  onApplied={onChanged}
                  entityKind="mix"
                  entityId={mixKey}
                  role="cover"
                  title={`${title} mix`}
                  hasOverride={Boolean(overrides[mixKey])}
                />,
                document.body,
              )
            : null}
        </>
      ) : null}
    </>
  );
}
