// Launcher for the Next.js 16 standalone web server (plain CommonJS, no build
// step). Every production launch of the web server runs THIS file, not
// server.js directly (installer, publish, release, dev stack).
//
// Why this exists (criterion 4): Next 16's proxy runs on a web NextRequest that
// has no socket peer, so it cannot read the real client IP. For a DIRECT LAN
// browser on http://<lan-ip>:3101 the backend then records 127.0.0.1 (the Next
// loopback peer), not the LAN IP, and the forwarded-header stripping has nothing
// safe to substitute. So this launcher stamps the real socket peer onto a
// dedicated header BEFORE Next sees the request, and the proxy decides trust
// from that peer.
//
// Two unforgeable signals the proxy reads:
//
//   1. process.env.F7FIVE0_LAUNCHER = "1". A client can only send headers; it
//      can never set process.env. The proxy treats the peer header as
//      trustworthy only when this flag is present, so a build run without the
//      launcher fails closed (records loopback) instead of honouring a forged
//      peer header.
//
//   2. The x-f7five0-peer header, OVERWRITTEN (never ??= or appended) with the
//      real socket remoteAddress on every request. Node's base-server.js does
//      `x-forwarded-for ??= socket.remoteAddress`, which keeps a client-sent
//      value; we must instead always clobber our own dedicated header so a
//      client-sent x-f7five0-peer is discarded.
process.env.F7FIVE0_LAUNCHER = "1";

const http = require("http");
const fs = require("fs");
const path = require("path");

// Give the web process the configured addresses from the install-root .env.
//
// Why here (criterion: redirects stay on the public host): the Next proxy's
// redirect to /login and its CSRF self-origin check build the site origin from
// PUBLIC_URL / APP_ALLOWED_HOSTS via lib/origin.ts (siteOriginFromHeaders). The
// service env install.ps1 writes never carried those, so a public hostname
// failed the allowlist and the redirect fell back to http://127.0.0.1:3001.
// The .env lives at the install root, not the web folder, and server.js never
// loads it. Reading it in the launcher fixes every path at once: install sets
// F7FIVE0_ENV_FILE, and remote-access.ps1 writes a new PUBLIC_URL to the same
// .env then restarts F7FIVE0-Web, so the restart picks it up with no NSSM env
// refresh. A real service-env value still wins (we never overwrite one).
function loadEnvFile() {
  const envPath =
    process.env.F7FIVE0_ENV_FILE || path.join(__dirname, "..", ".env");
  let text;
  try {
    text = fs.readFileSync(envPath, "utf8");
  } catch {
    return; // no .env (dev/standalone run): leave process.env as-is
  }
  // Only the addresses the web origin helper needs. Other keys stay backend-only.
  const wanted = new Set(["PUBLIC_URL", "HOME_URL", "APP_ALLOWED_HOSTS"]);
  for (const line of text.split(/\r?\n/)) {
    const s = line.trim();
    if (!s || s.startsWith("#")) continue;
    const eq = s.indexOf("=");
    if (eq < 0) continue;
    const key = s.slice(0, eq).trim();
    if (!wanted.has(key)) continue;
    // An explicit service-env value wins over the file (dotenv convention).
    if (process.env[key] !== undefined && process.env[key] !== "") continue;
    let val = s.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (val) process.env[key] = val;
  }
}
loadEnvFile();

// Hook every http.Server so that for each "request" event we overwrite the peer
// header on the Node request before Next's handler runs. Next's standalone
// server.js creates its own http.Server, so hooking the prototype catches it
// without us needing a reference to the server instance.
const origEmit = http.Server.prototype.emit;
http.Server.prototype.emit = function (event, ...args) {
  if (event === "request") {
    const req = args[0];
    if (req && req.headers) {
      // Always overwrite: discard any client-sent x-f7five0-peer, stamp the
      // real socket peer (empty string if somehow unavailable, which the proxy
      // treats as "no peer" and fails closed).
      req.headers["x-f7five0-peer"] =
        (req.socket && req.socket.remoteAddress) || "";
    }
  }
  return origEmit.call(this, event, ...args);
};

// Hand off to the standalone server sitting next to this launcher.
require("./server.js");
