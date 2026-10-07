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
