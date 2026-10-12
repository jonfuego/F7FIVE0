// A show tile for the Podcasts page: the show art on a square cover, the title
// and author under it. Plain text only; a description is never rendered here.

import Link from "next/link";
import type { CSSProperties } from "react";
import { artSized } from "@/lib/art-url";
import { colorForTitle, hueFromString } from "@/lib/format";
import type { PodcastShow } from "@/lib/types";

export function PodcastTile({ show }: { show: PodcastShow }) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(show.title),
    ["--ph" as never]: String(hueFromString(show.title)),
  };
  const sub = show.author || (show.source === "local" ? "On this server" : "");
  return (
    <Link href={`/podcasts/${show.id}`} className="sq-card" style={tint} aria-label={show.title}>
      <div className="cover">
        <div className="keyart-mini" />
        {show.art_url ? (
          <img
            src={artSized(show.art_url, 300) ?? show.art_url}
            alt=""
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
      </div>
      <div className="info">
        <div className="t">{show.title}</div>
        {sub ? <div className="s">{sub}</div> : null}
      </div>
    </Link>
  );
}
