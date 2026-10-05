// Render the Inno Setup wizard images and the Setup/uninstall icons for
// F7FIVE0 from the design-system marks in design/logos. Run via:
//
//   cd installer/branding-src
//   npm install            (sharp + png-to-ico, pinned)
//   npm run generate
//
// Outputs land in installer/branding/ and are committed to the repo so the
// CI Inno compile just reads them (no rasteriser needed in the Release job).
//
// Sources (design/logos, the export of the F7FIVE0 Design System artifact):
//   f7five0-mark.svg      honeycomb mark with the red/white front cell and the
//                         black F. Used for the large welcome/finish panel.
//   f7five0-app-icon.svg  the same comb on an opaque white tile. Used for the
//                         small inner-page image and the .ico.
//
// Logo rules (from the task note and design/logos comments): the mark is only
// ever black, hive red (#9C0404) and white, never reversed. The wizard panels
// are not guaranteed white, so every mark sits on a solid white plate here.
// Inno Setup 6.3.0+ reads PNG for WizardImageFile/WizardSmallImageFile and
// picks the closest size from a comma-separated list, which covers 100%-200%
// DPI. Icons are a multi-size .ico.

import sharp from "sharp";
import pngToIco from "png-to-ico";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const installerDir = path.resolve(here, "..");
const repoRoot = path.resolve(installerDir, "..");
const logosDir = path.join(repoRoot, "design", "logos");
const outDir = path.join(installerDir, "branding");

const MARK_SVG = path.join(logosDir, "f7five0-mark.svg");
const APP_ICON_SVG = path.join(logosDir, "f7five0-app-icon.svg");

const WHITE = { r: 255, g: 255, b: 255, alpha: 1 };

// Inno's default wizard image is 164x314 at 100%; the small image is 55x58.
// Scale both up to 200% so a comma-separated list covers 100% to 200% DPI.
const WIZARD_BASE = { w: 164, h: 314 };
const SMALL_BASE = { w: 55, h: 58 };
const SCALES = [1.0, 1.25, 1.5, 2.0];

function scaled(base, factor) {
  return { w: Math.round(base.w * factor), h: Math.round(base.h * factor) };
}

// Suffix for the extra sizes in the file name (100 -> "", 125 -> "-125", ...).
function suffix(factor) {
  return factor === 1.0 ? "" : `-${Math.round(factor * 100)}`;
}

async function ensureOutDir() {
  await fs.rm(outDir, { recursive: true, force: true });
  await fs.mkdir(outDir, { recursive: true });
}

// A mark centred on a solid white plate at the given pixel size. The comb is
// rendered big (high density) then contained with padding so it never touches
// the edges, which keeps it crisp and keeps the white plate visible.
async function renderOnWhite(svgPath, w, h, outName, markFraction) {
  const out = path.join(outDir, outName);
  // Render the mark into a box that is markFraction of the smaller side.
  const box = Math.round(Math.min(w, h) * markFraction);
  const mark = await sharp(svgPath, { density: 512 })
    .resize(box, box, { fit: "contain", background: { r: 255, g: 255, b: 255, alpha: 0 } })
    .png()
    .toBuffer();
  await sharp({ create: { width: w, height: h, channels: 3, background: "#ffffff" } })
    .composite([{ input: mark, gravity: "centre" }])
    .png()
    .toFile(out);
  console.log(`[branding] ${outName} ${w}x${h}`);
}

async function renderWizardImages() {
  // Large left panel: the honeycomb mark on a white plate.
  for (const f of SCALES) {
    const { w, h } = scaled(WIZARD_BASE, f);
    await renderOnWhite(MARK_SVG, w, h, `wizard-image${suffix(f)}.png`, 0.72);
  }
  // Small top-right image on inner pages: the app-icon tile (already white).
  for (const f of SCALES) {
    const { w, h } = scaled(SMALL_BASE, f);
    await renderOnWhite(APP_ICON_SVG, w, h, `wizard-small${suffix(f)}.png`, 0.92);
  }
}

async function renderIcon() {
  // Multi-size .ico from the app-icon tile for SetupIconFile and
  // UninstallDisplayIcon. Windows picks the size it needs from these.
  const sizes = [16, 24, 32, 48, 64, 128, 256];
  const buffers = [];
  for (const s of sizes) {
    const png = await sharp(APP_ICON_SVG, { density: 512 })
      .resize(s, s, { fit: "contain", background: WHITE })
      .flatten({ background: "#ffffff" })
      .png()
      .toBuffer();
    buffers.push(png);
  }
  const ico = await pngToIco(buffers);
  const out = path.join(outDir, "f7five0.ico");
  await fs.writeFile(out, ico);
  console.log(`[branding] f7five0.ico (${sizes.join(", ")})`);
}

async function main() {
  await ensureOutDir();
  await renderWizardImages();
  await renderIcon();
  console.log("[branding] done.");
}

main().catch((err) => {
  console.error("[branding] failed:", err);
  process.exit(1);
});
