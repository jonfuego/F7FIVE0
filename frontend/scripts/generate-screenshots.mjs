// Capture PWA manifest screenshots into frontend/public/screenshots/.
// Run via: npm run screenshots
//
// Env:
//   MH_URL         Base URL. Default http://localhost:3001.
//   MH_USERNAME    Login username. Required.
//   MH_PASSWORD    Login password. If unset, the script captures the login
//                  page itself; the screenshots still have the right pixel
//                  dimensions but show the unauthenticated entry view.
//   MH_INSECURE    If set to "1", ignores TLS errors. Useful when MH_URL
//                  points at a self-signed dev cert.
//
// Outputs:
//   screenshot-mobile-1.png     (390x844, /        )
//   screenshot-mobile-2.png     (390x844, /music   )
//   screenshot-desktop-1.png    (1280x720, /movies )

import { chromium } from "playwright";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoFrontend = path.resolve(here, "..");
const outDir = path.join(repoFrontend, "public", "screenshots");

const BASE_URL = process.env.MH_URL ?? "http://localhost:3001";
const USERNAME = process.env.MH_USERNAME ?? "";
const PASSWORD = process.env.MH_PASSWORD ?? "";
const INSECURE = process.env.MH_INSECURE === "1";

const SHOTS = [
  { name: "screenshot-mobile-1.png", width: 390, height: 844, route: "/" },
  { name: "screenshot-mobile-2.png", width: 390, height: 844, route: "/music" },
  { name: "screenshot-desktop-1.png", width: 1280, height: 720, route: "/movies" },
];

async function ensureOutDir() {
  await fs.mkdir(outDir, { recursive: true });
}

async function loginIfPossible(context) {
  if (!PASSWORD) {
    console.warn("[screenshots] MH_PASSWORD unset; capturing unauthenticated views.");
    return false;
  }
  const page = await context.newPage();
  try {
    const res = await page.request.post(`${BASE_URL}/api/session/login`, {
      data: { username: USERNAME, password: PASSWORD },
      headers: { "content-type": "application/json" },
    });
    if (!res.ok()) {
      console.warn(`[screenshots] login failed (${res.status()}); capturing unauthenticated views.`);
      return false;
    }
    return true;
  } catch (err) {
    console.warn(`[screenshots] login error: ${err?.message ?? err}`);
    return false;
  } finally {
    await page.close();
  }
}

async function capture(browser, ctxOpts, shot, authed) {
  const context = await browser.newContext({
    ...ctxOpts,
    viewport: { width: shot.width, height: shot.height },
    deviceScaleFactor: 1,
    ignoreHTTPSErrors: INSECURE,
  });
  if (authed) {
    await loginIfPossible(context);
  }
  const page = await context.newPage();
  const url = new URL(shot.route, BASE_URL).toString();
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 20_000 });
  } catch {
    // Fall back to a softer wait if networkidle never settles.
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20_000 });
  }
  await page.waitForTimeout(800);
  const out = path.join(outDir, shot.name);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`[screenshots] ${shot.name} ${shot.width}x${shot.height} <- ${url}`);
  await context.close();
}

async function main() {
  await ensureOutDir();
  const browser = await chromium.launch({ headless: true });
  try {
    // Pre-authenticate once and serialize cookies for reuse if possible.
    const ctxOpts = {};
    let authed = false;
    if (PASSWORD) {
      const probe = await browser.newContext({ ignoreHTTPSErrors: INSECURE });
      authed = await loginIfPossible(probe);
      if (authed) {
        const state = await probe.storageState();
        ctxOpts.storageState = state;
      }
      await probe.close();
    }
    for (const shot of SHOTS) {
      await capture(browser, ctxOpts, shot, false);
    }
  } finally {
    await browser.close();
  }
  console.log("[screenshots] done.");
}

main().catch((err) => {
  console.error("[screenshots] failed:", err);
  process.exit(1);
});
