/* Generate F7FIVE0 launcher / adaptive / splash / notification assets from the
 * web brand mark (F7FIVE0/frontend/app/icon.svg): amber play triangle on the
 * dark theme background (#0b0604). Build-time only; sharp is not a runtime dep.
 */
const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const BG = "#0b0604";
const AMBER = "#f59e0b";
const out = path.join(__dirname, "..", "assets");
fs.mkdirSync(out, { recursive: true });

// Full-bleed icon: rounded-dark tile + centered amber triangle.
function iconSvg(size, { bg = "#0a0a0a", radius = 0.22, pad = 0.28 } = {}) {
  const r = Math.round(size * radius);
  const p = size * pad;
  const x1 = p, y1 = p, x2 = p, y2 = size - p;
  const x3 = size - p * 0.9, ymid = size / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" rx="${r}" fill="${bg}"/>
  <path d="M${x1} ${y1} L${x2} ${y2} L${x3} ${ymid} Z" fill="${AMBER}"/>
</svg>`;
}

// Adaptive foreground: transparent background (the OS applies the mask + a
// separate background color), triangle inset so the mask never clips it.
function adaptiveForegroundSvg(size) {
  const p = size * 0.34;
  const x3 = size - p * 0.95, ymid = size / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <path d="M${p} ${p} L${p} ${size - p} L${x3} ${ymid} Z" fill="${AMBER}"/>
</svg>`;
}

function splashSvg(size) {
  const c = size / 2;
  const t = size * 0.16;
  const x3 = c + t * 1.1;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" fill="${BG}"/>
  <path d="M${c - t} ${c - t} L${c - t} ${c + t} L${x3} ${c} Z" fill="${AMBER}"/>
</svg>`;
}

// Monochrome notification small icon (Android renders it as a silhouette).
function notificationSvg(size) {
  const p = size * 0.3;
  const x3 = size - p * 0.9, ymid = size / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <path d="M${p} ${p} L${p} ${size - p} L${x3} ${ymid} Z" fill="#ffffff"/>
</svg>`;
}

async function png(svg, file, size) {
  await sharp(Buffer.from(svg)).resize(size, size).png().toFile(path.join(out, file));
  console.log("wrote", file, size);
}

(async () => {
  await png(iconSvg(1024), "icon.png", 1024);
  await png(adaptiveForegroundSvg(1024), "adaptive-icon.png", 1024);
  await png(splashSvg(1024), "splash.png", 1024);
  await png(notificationSvg(96), "notification-icon.png", 96);
  await png(iconSvg(48, { radius: 0.5 }), "favicon.png", 48);
  console.log("assets generated");
})();
