// node:test for the launcher's header-stamp/overwrite logic. Runs the REAL
// server-wrapper.js: it sets F7FIVE0_LAUNCHER and hooks http.Server.prototype
// .emit, then require()s ./server.js. We stub ./server.js (via a temp copy of
// the wrapper whose require target is a tiny http server) so we can fire a real
// request carrying a bogus x-f7five0-peer and confirm the hook OVERWRITES it
// with the socket peer, and that F7FIVE0_LAUNCHER is set.
//
// Run: node --test frontend/server-wrapper.test.js

const { test } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

test("server-wrapper stamps F7FIVE0_LAUNCHER and overwrites a forged peer header", async () => {
  // Stage the real wrapper next to a stub server.js in a temp dir, so
  // require("./server.js") resolves to our stub. The stub records the peer
  // header the handler sees and sets the result on a shared object.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "f7wrap-"));
  const wrapperSrc = fs.readFileSync(
    path.join(__dirname, "server-wrapper.js"),
    "utf8",
  );
  fs.writeFileSync(path.join(dir, "server-wrapper.js"), wrapperSrc);

  // The stub "server.js": a plain http.Server that echoes the peer header it
  // received back to the client. Because the wrapper hooked the prototype
  // before this file loads, the handler must see the OVERWRITTEN header.
  const stub = `
    const http = require("http");
    const srv = http.createServer((req, res) => {
      res.end(JSON.stringify({ peer: req.headers["x-f7five0-peer"] ?? null }));
    });
    srv.listen(0, "127.0.0.1", () => {
      process.send({ port: srv.address().port, launcher: process.env.F7FIVE0_LAUNCHER });
    });
  `;
  fs.writeFileSync(path.join(dir, "server.js"), stub);

  const { fork } = require("node:child_process");
  const child = fork(path.join(dir, "server-wrapper.js"), [], {
    stdio: ["ignore", "ignore", "ignore", "ipc"],
  });

  try {
    const { port, launcher } = await new Promise((resolve, reject) => {
      child.once("message", resolve);
      child.once("error", reject);
      setTimeout(() => reject(new Error("stub server did not start")), 5000);
    });

    // The flag is visible in the launcher process.
    assert.equal(launcher, "1");

    // Send a request with a BOGUS x-f7five0-peer; the hook must overwrite it
    // with the real socket peer (127.0.0.1 for this loopback connection).
    const body = await new Promise((resolve, reject) => {
      const r = http.request(
        { host: "127.0.0.1", port, path: "/", method: "GET",
          headers: { "x-f7five0-peer": "203.0.113.9" } },
        (res) => {
          let b = "";
          res.on("data", (c) => (b += c));
          res.on("end", () => resolve(b));
        },
      );
      r.on("error", reject);
      r.end();
    });

    const seen = JSON.parse(body).peer;
    assert.notEqual(seen, "203.0.113.9", "the forged peer header was not overwritten");
    assert.match(seen, /^(::ffff:)?127\.0\.0\.1$|^::1$/, `unexpected peer ${seen}`);
  } finally {
    child.kill();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
