"use client";

import type { CastStatus } from "../lib/cast";

// Thin wrapper around the SDK-provided <google-cast-launcher> custom element.
// The element is registered by the Cast SDK after it loads; before that it's
// unknown to the DOM. Rendering it is still safe — it shows up as an unknown
// tag that takes no layout space. Once the SDK registers it, the element
// self-styles as a button and handles device picker + session lifecycle on
// its own.
//
// We still gate visibility on `status` so the button doesn't appear on
// browsers that will never get Cast support (the SDK never loads on those,
// so the element never upgrades). That avoids a confusing dead button for
// Firefox/Safari users.

interface CastButtonProps {
  status: CastStatus;
  className?: string;
}

export default function CastButton({ status, className = "" }: CastButtonProps) {
  if (status === "unavailable") return null;

  return (
    <google-cast-launcher
      // The launcher is a custom element, not a button; the SDK swaps it to
      // a clickable icon at upgrade time. Tailwind sizing works via the
      // custom element's default block-level layout.
      cast-icon-color="#ffffff"
      className={`inline-block h-6 w-6 cursor-pointer ${className}`.trim()}
      style={{ width: 24, height: 24 }}
    />
  );
}
