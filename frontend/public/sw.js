// F7FIVE0 Service Worker.
//
// Scope: '/'. Lives at /sw.js so the default scope covers the whole origin.
// Purpose: render a system notification with prev / play-pause / next
// transport buttons whenever the dock has an active queue item, on
// browsers (Firefox Android in particular) where the Media Session API
// alone does not surface those controls.
//
// This SW does not register a fetch handler. Pass-through only.
// Offline / caching / push notifications are out of scope.

function log(...args) {
  // eslint-disable-next-line no-console
  console.log("[mh-sw]", ...args);
}

self.addEventListener("install", (event) => {
  log("install");
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  log("activate");
  event.waitUntil(self.clients.claim());
});

// No fetch handler. Future caching can land later under a separate handoff.

self.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || typeof data !== "object") return;

  if (data.type === "mh:notif:show") {
    const p = data.payload || {};
    const title = p.title || "Now playing";
    const artist = p.artist || "";
    const album = p.album || "";
    const isPlaying = !!p.isPlaying;
    const artworkUrl = p.artworkUrl || null;
    const mediaFileId = p.mediaFileId || null;

    const bodyLines = [];
    if (artist) bodyLines.push(artist);
    if (album) bodyLines.push(album);
    const body = bodyLines.join("\n");

    const options = {
      body,
      icon: artworkUrl || "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      tag: "mh-now-playing",
      renotify: false,
      silent: true,
      requireInteraction: true,
      actions: [
        { action: "prev", title: "Previous", icon: "/icons/action-prev.png" },
        {
          action: "play",
          title: isPlaying ? "Pause" : "Play",
          icon: isPlaying ? "/icons/action-pause.png" : "/icons/action-play.png",
        },
        { action: "next", title: "Next", icon: "/icons/action-next.png" },
      ],
      data: { mediaFileId },
    };

    event.waitUntil(
      self.registration.showNotification(title, options).catch((err) => {
        log("showNotification failed", err);
      }),
    );
    return;
  }

  if (data.type === "mh:notif:hide") {
    event.waitUntil(
      self.registration
        .getNotifications({ tag: "mh-now-playing" })
        .then((notes) => {
          for (const n of notes) {
            try { n.close(); } catch (e) { /* ignore */ }
          }
        })
        .catch((err) => {
          log("hide failed", err);
        }),
    );
    return;
  }
});

self.addEventListener("notificationclick", (event) => {
  const action = event.action;
  log("notificationclick", action);
  if (action !== "prev" && action !== "play" && action !== "next") {
    // Body click with no action: focus the page.
    event.waitUntil(focusOrOpen());
    return;
  }

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then(async (clients) => {
        const message = { type: "mh:notif:action", action };
        if (clients.length > 0) {
          for (const c of clients) {
            try { c.postMessage(message); } catch (e) { /* ignore */ }
          }
          // Bring one of them forward so the page is visible after action.
          try { await clients[0].focus(); } catch (e) { /* ignore */ }
          return;
        }
        // No open clients: open the root and post the action once it loads.
        const win = await self.clients.openWindow("/");
        if (win) {
          try { win.postMessage(message); } catch (e) { /* ignore */ }
        }
      }),
  );
});

self.addEventListener("notificationclose", () => {
  // No-op. Dismissing the notification does not stop playback; the dock keeps
  // playing and the next state change will rebuild the notification.
});

async function focusOrOpen() {
  const clients = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  });
  if (clients.length > 0) {
    try { await clients[0].focus(); } catch (e) { /* ignore */ }
    return;
  }
  await self.clients.openWindow("/");
}
