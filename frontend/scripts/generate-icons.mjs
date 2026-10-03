// Render PWA icons from the design system marks in design/logos into
// frontend/public/icons/. Run via: npm run icons
//
// Sources (design/logos, the export of the F7FIVE0 Design System artifact):
//   f7five0-app-icon.svg   white app-icon tile -> standard + apple-touch icons
//   f7five0-maskable.svg   maskable (content in the inner safe zone) -> maskable icons
//   f7five0-badge-mono.svg one-color notification badge -> badge-72
//
// Outputs:
//   icon-192.png, icon-512.png                   (standard, full-bleed)
//   icon-maskable-192.png, icon-maskable-512.png (content in inner 80% safe zone)
//   apple-touch-icon-180.png                     (no transparency, opaque white)
//   badge-72.png                                 (monochrome, white-on-transparent)
//   action-prev.png, action-play.png,
//   action-pause.png, action-next.png            (96x96 monochrome transport glyphs)
//
// The honeycomb mark is only ever black, hive red and white, so the launcher
// and PWA icons sit on the white app-icon tile. The transport-glyph PNGs feed
// the OS media notification and stay white-on-transparent.

import sharp from "sharp";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoFrontend = path.resolve(here, "..");
const repoRoot = path.resolve(repoFrontend, "..");
const logosDir = path.join(repoRoot, "design", "logos");
const outDir = path.join(repoFrontend, "public", "icons");

const APP_ICON_SVG = path.join(logosDir, "f7five0-app-icon.svg");
const MASKABLE_SVG = path.join(logosDir, "f7five0-maskable.svg");
const BADGE_SVG = path.join(logosDir, "f7five0-badge-mono.svg");

async function ensureOutDir() {
  await fs.mkdir(outDir, { recursive: true });
}

async function renderStandard(svgPath, size, outName) {
  const out = path.join(outDir, outName);
  await sharp(svgPath, { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size}`);
}

async function renderMaskable(svgPath, size, outName) {
  // The maskable mark already carries its safe-zone layout; render it full
  // bleed so Android's mask crops into the padding, not the comb.
  const out = path.join(outDir, outName);
  await sharp(svgPath, { density: 384 })
    .resize(size, size, { fit: "cover" })
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size} (maskable)`);
}

async function renderAppleTouch(svgPath, size, outName) {
  // iOS rejects transparent backgrounds and rounds corners itself, so
  // composite the white tile onto an opaque white background.
  const out = path.join(outDir, outName);
  const innerPng = await sharp(svgPath, { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 255, g: 255, b: 255, alpha: 1 } })
    .png()
    .toBuffer();
  await sharp({
    create: { width: size, height: size, channels: 3, background: "#ffffff" },
  })
    .composite([{ input: innerPng, top: 0, left: 0 }])
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size} (apple-touch)`);
}

async function renderBadge(svgPath, size, outName) {
  // Android notification badge: single-color silhouette on transparent.
  const out = path.join(outDir, outName);
  await sharp(svgPath, { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size} (badge)`);
}

async function renderActionGlyph(svgInner, size, outName) {
  const out = path.join(outDir, outName);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
    <rect width="96" height="96" fill="none"/>
    ${svgInner}
  </svg>`;
  await sharp(Buffer.from(svg, "utf8"), { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size} (action)`);
}

async function main() {
  await ensureOutDir();

  await renderStandard(APP_ICON_SVG, 192, "icon-192.png");
  await renderStandard(APP_ICON_SVG, 512, "icon-512.png");
  await renderMaskable(MASKABLE_SVG, 192, "icon-maskable-192.png");
  await renderMaskable(MASKABLE_SVG, 512, "icon-maskable-512.png");
  await renderAppleTouch(APP_ICON_SVG, 180, "apple-touch-icon-180.png");
  await renderBadge(BADGE_SVG, 72, "badge-72.png");

  const W = "#ffffff";
  const prev = `<g fill="${W}"><rect x="20" y="20" width="10" height="56"/><polygon points="76,20 76,76 36,48"/></g>`;
  const next = `<g fill="${W}"><rect x="66" y="20" width="10" height="56"/><polygon points="20,20 20,76 60,48"/></g>`;
  const play = `<polygon points="28,18 28,78 78,48" fill="${W}"/>`;
  const pause = `<g fill="${W}"><rect x="24" y="18" width="16" height="60"/><rect x="56" y="18" width="16" height="60"/></g>`;
  await renderActionGlyph(prev, 96, "action-prev.png");
  await renderActionGlyph(play, 96, "action-play.png");
  await renderActionGlyph(pause, 96, "action-pause.png");
  await renderActionGlyph(next, 96, "action-next.png");

  console.log("[icons] done.");
}

main().catch((err) => {
  console.error("[icons] failed:", err);
  process.exit(1);
});
