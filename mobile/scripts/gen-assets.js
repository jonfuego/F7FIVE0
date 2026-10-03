/* Generate F7FIVE0 launcher / adaptive / splash / notification assets from the
 * design system marks in design/logos (the export of the F7FIVE0 Design System
 * artifact). Build-time only; sharp is not a runtime dep.
 *
 * Sources (design/logos):
 *   f7five0-app-icon.svg            white app-icon tile  -> icon.png, splash.png, favicon.png
 *   f7five0-adaptive-foreground.svg transparent fg comb  -> adaptive-icon.png (OS fills #FFFFFF behind)
 *   f7five0-badge-mono.svg          one-color silhouette -> notification-icon.png
 *
 * The honeycomb mark is only ever black, hive red and white, so the launcher
 * icon is the white tile. The splash shows that white tile centered on the
 * #000000 splash background set in app.config.ts.
 */
const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const logos = path.resolve(__dirname, "../../design/logos");
const out = path.join(__dirname, "..", "assets");
fs.mkdirSync(out, { recursive: true });

const APP_ICON = path.join(logos, "f7five0-app-icon.svg");
const ADAPTIVE = path.join(logos, "f7five0-adaptive-foreground.svg");
const BADGE = path.join(logos, "f7five0-badge-mono.svg");

async function render(src, file, size) {
  await sharp(src, { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toFile(path.join(out, file));
  console.log("wrote", file, size);
}

(async () => {
  await render(APP_ICON, "icon.png", 1024);
  await render(ADAPTIVE, "adaptive-icon.png", 1024);
  await render(APP_ICON, "splash.png", 1024);
  await render(BADGE, "notification-icon.png", 96);
  await render(APP_ICON, "favicon.png", 48);
  console.log("assets generated");
})();
