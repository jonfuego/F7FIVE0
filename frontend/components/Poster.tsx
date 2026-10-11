// The poster frame used by MediaCard and ContinueWatchingCard. Renders
// real art when posterPath is set, otherwise a flat surface-2 placeholder.
//
// Visual: aspect 2/3 by default, 1/1 for albums/tracks, 16/9 for the
// continue rail. The frame's hover and focus treatment is the HIVE offset
// (shadow-hive) plus the focus ring, styled by the .poster .frame rules in
// globals.css; the shadow-hive utilities below mirror it for grouped hover
// and keyboard focus.

"use client";

import { useState } from "react";
import { artSized } from "@/lib/art-url";

type AspectRatio = "poster" | "square" | "wide";

type Props = {
  src: string | null;
  alt: string;
  aspect?: AspectRatio;
};

const ASPECT_STYLE: Record<AspectRatio, string> = {
  poster: "2/3",
  square: "1/1",
  wide: "16/9",
};

export function Poster({ src, alt, aspect = "poster" }: Props) {
  const [broken, setBroken] = useState(false);
  const showFallback = !src || broken;

  return (
    <div
      className="frame group-hover:shadow-hive focus-visible:shadow-hive"
      style={{ aspectRatio: ASPECT_STYLE[aspect] }}
    >
      <div className="keyart-mini" />
      {!showFallback ? (
        <img
          src={artSized(src, aspect === "wide" ? 600 : 300) ?? ""}
          alt={alt}
          loading="lazy"
          decoding="async"
          onError={() => setBroken(true)}
          className="real-art"
        />
      ) : null}
    </div>
  );
}
