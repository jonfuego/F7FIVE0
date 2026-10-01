// Render PWA icons from frontend/app/icon.svg into frontend/public/icons/.
// Run via: npm run icons
//
// Outputs:
//   icon-192.png, icon-512.png                 (standard, full-bleed)
//   icon-maskable-192.png, icon-maskable-512.png (content in inner 80% safe zone)
//   apple-touch-icon-180.png                   (no transparency, opaque background)
//   badge-72.png                               (monochrome white-on-transparent)
//   action-prev.png, action-play.png,
//   action-pause.png, action-next.png          (96x96 monochrome transport glyphs)
//
// The transport-glyph PNGs are rendered from inline SVG strings so the
// existing icon.svg only needs to provide the brand mark.

import sharp from "sharp";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoFrontend = path.resolve(here, "..");
const iconSvgPath = path.join(repoFrontend, "app", "icon.svg");
const outDir = path.join(repoFrontend, "public", "icons");

const BRAND_BG = "#0a0a0a";
const BRAND_FG = "#f59e0b";
const SURFACE_BG = "#181614";

const FALLBACK_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="${BRAND_BG}"/>
  <path d="M22 18 L22 46 L46 32 Z" fill="${BRAND_FG}"/>
</svg>`;

async function ensureIconSource() {
  try {
    return await fs.readFile(iconSvgPath);
  } catch {
    await fs.writeFile(iconSvgPath, FALLBACK_ICON_SVG, "utf8");
    console.log(`[icons] wrote fallback ${iconSvgPath}`);
    return Buffer.from(FALLBACK_ICON_SVG, "utf8");
  }
}

async function ensureOutDir() {
  await fs.mkdir(outDir, { recursive: true });
}

async function renderStandard(svg, size, outName) {
  const out = path.join(outDir, outName);
  await sharp(svg, { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size}`);
}

async function renderMaskable(svg, size, outName) {
  // Content occupies inner 80% (safe zone) on a solid brand background so
  // Android's mask doesn't crop the logo and there is no transparent margin
  // for the launcher to fill.
  const out = path.join(outDir, outName);
  const inner = Math.round(size * 0.8);
  const innerPng = await sharp(svg, { density: 384 })
    .resize(inner, inner, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();
  const offset = Math.round((size - inner) / 2);
  await sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: BRAND_BG,
    },
  })
    .composite([{ input: innerPng, top: offset, left: offset }])
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size} (maskable)`);
}

async function renderAppleTouch(svg, size, outName) {
  // iOS rejects transparent backgrounds and rounds corners itself, so
  // composite the icon onto an opaque brand-color background.
  const out = path.join(outDir, outName);
  const inner = Math.round(size * 0.78);
  const innerPng = await sharp(svg, { density: 384 })
    .resize(inner, inner, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();
  const offset = Math.round((size - inner) / 2);
  await sharp({
    create: { width: size, height: size, channels: 3, background: BRAND_BG },
  })
    .composite([{ input: innerPng, top: offset, left: offset }])
    .png()
    .toFile(out);
  console.log(`[icons] ${outName} ${size}x${size} (apple-touch)`);
}

async function renderBadge(size, outName) {
  // Android notification badge: monochrome white-on-transparent silhouette.
  const out = path.join(outDir, outName);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
    <path d="M22 18 L22 46 L46 32 Z" fill="#ffffff" transform="scale(0.45) translate(0, 0)"/>
    <circle cx="12" cy="12" r="9" fill="none" stroke="#ffffff" stroke-width="2"/>
    <path d="M9 8 L9 16 L17 12 Z" fill="#ffffff"/>
  </svg>`;
  await sharp(Buffer.from(svg, "utf8"), { density: 384 })
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
  const svg = await ensureIconSource();

  await renderStandard(svg, 192, "icon-192.png");
  await renderStandard(svg, 512, "icon-512.png");
  await renderMaskable(svg, 192, "icon-maskable-192.png");
  await renderMaskable(svg, 512, "icon-maskable-512.png");
  await renderAppleTouch(svg, 180, "apple-touch-icon-180.png");
  await renderBadge(72, "badge-72.png");

  const W = "#ffffff";
  const prev = `<g fill="${W}"><rect x="20" y="20" width="10" height="56"/><polygon points="76,20 76,76 36,48"/></g>`;
  const next = `<g fill="${W}"><rect x="66" y="20" width="10" height="56"/><polygon points="20,20 20,76 60,48"/></g>`;
  const play = `<polygon points="28,18 28,78 78,48" fill="${W}"/>`;
  const pause = `<g fill="${W}"><rect x="24" y="18" width="16" height="60"/><rect x="56" y="18" width="16" height="60"/></g>`;
  await renderActionGlyph(prev, 96, "action-prev.png");
  await renderActionGlyph(play, 96, "action-play.png");
  await renderActionGlyph(pause, 96, "action-pause.png");
  await renderActionGlyph(next, 96, "action-next.png");

  // Touch SURFACE_BG so the constant is referenced; some bundlers strip
  // unused top-level consts otherwise.
  void SURFACE_BG;

  console.log("[icons] done.");
}

main().catch((err) => {
  console.error("[icons] failed:", err);
  process.exit(1);
});
