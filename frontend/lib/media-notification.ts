// Page-side helper for the SW-rendered media notification surface. Pairs
// with frontend/public/sw.js. Exists so MiniPlayer can keep the
// SW-driven notification in sync with the dock without touching the
// existing Media Session wiring.
//
// All exports SSR-safely no-op when window is undefined.

export type MediaNotificationPayload = {
  title: string;
  artist: string;
  album: string;
  artworkUrl: string | null;
  isPlaying: boolean;
  mediaFileId: string;
};

export type MediaNotificationAction = "prev" | "play" | "next";

type ActionMessage = { type: "mh:notif:action"; action: MediaNotificationAction };

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

// Chromium-family detection. Chrome, Edge, Opera, Brave, and Samsung Internet
// all surface the Media Session API at the OS level (lock screen widget,
// AVRCP over Bluetooth, etc.). On those browsers the SW now-playing card is
// redundant with the system widget and gets flagged by Chrome's abusive-
// notifications heuristic. Skip the SW path on Chromium and let Media Session
// own the OS surface; Firefox and installed-PWA Safari still get the card.
function isChromium(): boolean {
  if (!isBrowser()) return false;
  const uaData = (navigator as Navigator & {
    userAgentData?: { brands?: Array<{ brand?: string }> };
  }).userAgentData;
  if (uaData && Array.isArray(uaData.brands)) {
    for (const b of uaData.brands) {
      const brand = String(b?.brand || "").toLowerCase();
      if (
        brand.includes("chromium") ||
        brand.includes("google chrome") ||
        brand.includes("microsoft edge") ||
        brand.includes("opera")
      ) {
        return true;
      }
    }
    return false;
  }
  const ua = navigator.userAgent || "";
  if (/Firefox\//.test(ua)) return false;
  return /Chrom(e|ium)\//.test(ua);
}

export async function registerMediaServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!isBrowser()) return null;
  if (!("serviceWorker" in navigator)) return null;
  // On Chromium, unwind any prior install so existing devices stop firing the
  // now-redundant notification, then bail. Media Session covers the OS-level
  // transport surface there.
  if (isChromium()) {
    try {
      const regs = await navigator.serviceWorker.getRegistrations();
      for (const reg of regs) {
        try {
          const notes = await reg.getNotifications({ tag: "mh-now-playing" });
          for (const n of notes) {
            try { n.close(); } catch { /* ignore */ }
          }
        } catch { /* ignore */ }
        try { await reg.unregister(); } catch { /* ignore */ }
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[mh-notif] SW unregister failed", err);
    }
    return null;
  }
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    return reg;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[mh-notif] SW registration failed", err);
    return null;
  }
}

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!isBrowser()) return "denied";
  if (typeof Notification === "undefined") return "denied";
  // No reason to prompt on Chromium. Media Session is the OS surface there,
  // and a stray permission request feeds Chrome's abusive-notifications
  // classifier without any UX payoff.
  if (isChromium()) return Notification.permission;
  try {
    const result = await Notification.requestPermission();
    return result;
  } catch {
    return "denied";
  }
}

function canPostToSw(): boolean {
  if (!isBrowser()) return false;
  if (typeof Notification === "undefined") return false;
  if (Notification.permission !== "granted") return false;
  if (!("serviceWorker" in navigator)) return false;
  if (!navigator.serviceWorker.controller) return false;
  return true;
}

export async function showMediaNotification(payload: MediaNotificationPayload): Promise<void> {
  // Defense in depth: even if a stale SW controller is still attached on
  // Chromium between a deploy and a tab reload, do not post show messages.
  if (isChromium()) return;
  if (!canPostToSw()) return;
  try {
    navigator.serviceWorker.controller!.postMessage({ type: "mh:notif:show", payload });
  } catch {
    // best-effort
  }
}

export async function hideMediaNotification(): Promise<void> {
  if (!canPostToSw()) return;
  try {
    navigator.serviceWorker.controller!.postMessage({ type: "mh:notif:hide" });
  } catch {
    // best-effort
  }
}

export function subscribeToNotificationActions(
  handler: (action: MediaNotificationAction) => void,
): () => void {
  if (!isBrowser()) return () => {};
  if (!("serviceWorker" in navigator)) return () => {};
  const listener = (event: MessageEvent) => {
    const data = event.data as ActionMessage | undefined;
    if (!data || data.type !== "mh:notif:action") return;
    if (data.action !== "prev" && data.action !== "play" && data.action !== "next") return;
    handler(data.action);
  };
  navigator.serviceWorker.addEventListener("message", listener);
  return () => {
    navigator.serviceWorker.removeEventListener("message", listener);
  };
}
