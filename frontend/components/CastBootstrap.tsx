"use client";

import { useEffect } from "react";

// Loads the Google Cast CAF v3 sender SDK once, at app root, and initializes
// CastContext with F7FIVE0's options. Rendering is a side effect only; this
// component returns null.
//
// The SDK invokes `window.__onGCastApiAvailable(ok)` after its internal
// framework loads. `ok === true` means cast.framework is ready to use. On
// browsers without Cast support (Firefox, Safari, non-Chromium) the callback
// fires with `false` and we leave everything wired up but idle. The
// `<google-cast-launcher>` element hides itself in that case.
//
// Mounted once from `app/layout.tsx`. Safe to mount multiple times because
// the script tag check prevents a second load, but there's no reason to.

const SDK_SRC =
  "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";

let initialized = false;

function initCastContext() {
  if (initialized) return;
  if (typeof window === "undefined") return;
  if (!window.cast?.framework || !window.chrome?.cast) return;

  try {
    window.cast.framework.CastContext.getInstance().setOptions({
      receiverApplicationId:
        window.chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
      autoJoinPolicy: window.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
    });
    initialized = true;
  } catch (err) {
    // Re-initialization or options conflict. Not fatal; the default receiver
    // remains usable. Log for developer visibility only.
    console.warn("[cast] setOptions failed", err);
  }
}

export default function CastBootstrap() {
  useEffect(() => {
    if (typeof window === "undefined") return;

    // If the SDK already loaded (fast refresh, second mount), just
    // re-attempt init and exit.
    if (window.cast?.framework) {
      initCastContext();
      return;
    }

    // Wire the callback before injecting the script. The SDK invokes this
    // exactly once as part of its internal bootstrap.
    window.__onGCastApiAvailable = (ok: boolean) => {
      if (!ok) return;
      initCastContext();
    };

    // Avoid double-injecting the script tag across remounts.
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${SDK_SRC}"]`,
    );
    if (existing) return;

    const script = document.createElement("script");
    script.src = SDK_SRC;
    script.async = true;
    document.head.appendChild(script);
  }, []);

  return null;
}
