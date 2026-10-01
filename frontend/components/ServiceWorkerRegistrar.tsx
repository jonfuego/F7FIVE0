"use client";

import { useEffect } from "react";
import { registerMediaServiceWorker } from "@/lib/media-notification";

export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    void registerMediaServiceWorker();
  }, []);
  return null;
}
