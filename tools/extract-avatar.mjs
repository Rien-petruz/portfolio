// One-off: crops Peter's headshot out of the reference cover art into brand/assets/avatar.png.
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(root, "tools/source/reference-cover.png");
const CROP = { x: 69, y: 1007, w: 174, h: 174 }; // measured bounding box of the headshot ring
const OUT = 400;

const b64 = readFileSync(SRC).toString("base64");
const scale = OUT / CROP.w;

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: ["--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: OUT, height: OUT } });
await page.setContent(`<style>
  html,body{margin:0;width:${OUT}px;height:${OUT}px;overflow:hidden;background:#fff}
  img{position:absolute;transform-origin:0 0;
      transform:scale(${scale}) translate(${-CROP.x}px, ${-CROP.y}px);image-rendering:auto}
</style><img src="data:image/png;base64,${b64}">`);
await page.screenshot({ path: join(root, "brand/assets/avatar.png") });
await browser.close();
console.log("wrote brand/assets/avatar.png");
