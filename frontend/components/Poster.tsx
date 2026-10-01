// The poster frame used by MediaCard and ContinueWatchingCard. Renders
// real art when posterPath is set, otherwise a tinted gradient
// placeholder driven by the item's color (from --pg).
//
// Visual: aspect 2/3 by default, 1/1 for albums/tracks, 16/9 for the
// continue rail. The frame's color tint, hover lift, and amber outline
// are styled by the .poster .frame rules in globals.css.

"use client";

import { useState } from "react";

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
    <div className="frame" style={{ aspectRatio: ASPECT_STYLE[aspect] }}>
      <div className="keyart-mini" />
      {!showFallback ? (
        <img
          src={src ?? ""}
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
