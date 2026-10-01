// /music/artists is a thin alias for /music: the music landing page
// already renders the artist grid. The redirect keeps any old links
// pointing to /music/artists working without duplicating that grid here.

"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useScrollRestoration } from "@/lib/scroll-restoration";

export default function MusicArtistsPage() {
  useScrollRestoration();
  const router = useRouter();
  useEffect(() => {
    router.replace("/music");
  }, [router]);
  return null;
}
