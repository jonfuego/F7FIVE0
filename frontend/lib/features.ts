// Which optional integrations the server has turned on. Read once per page
// load from GET /api/client/features (no auth) and cached in memory.

"use client";

import { useEffect, useState } from "react";

export type Features = {
  requests: { enabled: boolean; movie: boolean; series: boolean };
  /** Address for use away from home (Tailscale / Cloudflare), if set up. */
  public_url?: string | null;
  /** Passkey sign-in. Off on home-only (plain http) installs. */
  passkeys?: { enabled: boolean; rp_id: string | null };
  /** Hardware (NVENC) transcoding on the server. */
  transcode?: { hardware: boolean };
};

const NONE: Features = { requests: { enabled: false, movie: false, series: false }, public_url: null, passkeys: { enabled: false, rp_id: null } };

let cached: Promise<Features> | null = null;

export function loadFeatures(): Promise<Features> {
  if (!cached) {
    cached = fetch("/api/client/features", { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<Features>) : NONE))
      .catch(() => NONE);
  }
  return cached;
}

/** null while loading, then the server's feature flags. */
export function useFeatures(): Features | null {
  const [features, setFeatures] = useState<Features | null>(null);
  useEffect(() => {
    let alive = true;
    loadFeatures().then((f) => {
      if (alive) setFeatures(f);
    });
    return () => {
      alive = false;
    };
  }, []);
  return features;
}
