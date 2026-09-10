// Renders a post's slides.json into PNG carousel slides.
//
//   node tools/render.mjs content/posts/001-idempotency
//   node tools/render.mjs --all
//
// Output lands in <postDir>/out/01.png, 02.png, ... plus contact-sheet.png.
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
import { readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, basename } from "node:path";
import { assets, css, slideHTML } from "./templates.mjs";

const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const brand = JSON.parse(readFileSync(join(root, "brand/brand.json"), "utf8"));
const a = assets(root, brand);

const args = process.argv.slice(2);
const postsRoot = join(root, "content/posts");
const dirs = args.includes("--all")
  ? readdirSync(postsRoot).filter((d) => existsSync(join(postsRoot, d, "slides.json"))).sort()
      .map((d) => join(postsRoot, d))
  : args.filter((x) => !x.startsWith("--")).map((p) => resolve(p));

if (!dirs.length) {
  console.error("usage: node tools/render.mjs <postDir> [...] | --all");
  process.exit(1);
}

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });

for (const dir of dirs) {
  const post = JSON.parse(readFileSync(join(dir, "slides.json"), "utf8"));
  const fmt = brand.formats[post.format || "square"];
  if (!fmt) throw new Error(`${basename(dir)}: unknown format "${post.format}"`);

  const outDir = join(dir, "out");
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  const page = await browser.newPage({
    viewport: { width: fmt.w, height: fmt.h },
    deviceScaleFactor: 1,
  });
  const style = css(brand, a, fmt);
  const total = post.slides.length;
  const files = [];

  for (let i = 0; i < total; i++) {
    const ctx = { brand, a, ctx: { n: i + 1, total, series: post.series || brand.series, last: i === total - 1 } };
    const body = slideHTML(post.slides[i], ctx);
    await page.setContent(`<style>${style}</style>${body}`, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);

    // Card bodies scale down to fit rather than clipping their last lines.
    // Binary search, because shrinking widens the compensated box and re-wraps
    // the text — so a first-guess ratio always overshoots.
    const scaled = await page.evaluate(() => {
      const out = [];
      for (const body of document.querySelectorAll(".win-body")) {
        const fit = body.querySelector(".win-fit");
        if (!fit) continue;
        const padB = parseFloat(getComputedStyle(body).paddingBottom) || 0;
        const fits = (k) => {
          fit.style.transform = k === 1 ? "" : `scale(${k})`;
          fit.style.width = k === 1 ? "100%" : `${100 / k}%`;
          const room = body.getBoundingClientRect().bottom - padB - fit.getBoundingClientRect().top;
          return fit.getBoundingClientRect().height <= room + 1;
        };
        if (fits(1)) continue;
        let lo = 0.6, hi = 1, best = 0.6;
        for (let i = 0; i < 14; i++) {
          const mid = (lo + hi) / 2;
          if (fits(mid)) { best = mid; lo = mid; } else hi = mid;
        }
        fits(best);
        out.push(best.toFixed(3));
      }
      return out;
    });
    for (const k of scaled) console.log(`    card auto-fit scale ${k}`);

    // Code blocks get auto-fitted: shrink the type until the listing fits its
    // window on both axes, rather than silently clipping the last lines.
    const fitted = await page.evaluate(() => {
      const results = [];
      for (const pre of document.querySelectorAll(".codewin pre")) {
        const code = pre.querySelector("code");
        const start = parseFloat(getComputedStyle(code).fontSize);
        let size = start;
        const fits = () =>
          pre.scrollHeight <= pre.clientHeight + 1 && pre.scrollWidth <= pre.clientWidth + 1;
        while (size > 15 && !fits()) {
          size -= 0.5;
          code.style.fontSize = size + "px";
        }
        if (size !== start) results.push({ from: start, to: size, ok: fits() });
      }
      return results;
    });
    for (const f of fitted) {
      console.log(`    code auto-fit ${f.from}px → ${f.to}px${f.ok ? "" : "  ! still clipped"}`);
    }

    // Overflow check walks the whole tree — an inner card can clip while the
    // outer frame looks fine, which is exactly how copy goes missing.
    const clipped = await page.evaluate(() => {
      const bad = [];
      const TOL = 2;
      for (const el of document.querySelectorAll(".slide, .slide *")) {
        const cs = getComputedStyle(el);
        if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
        const box = el.getBoundingClientRect();
        let right = -Infinity, bottom = -Infinity;
        const flow = [...el.children].filter((ch) => getComputedStyle(ch).position !== "absolute");
        if (flow.length) {
          for (const ch of el.children) {
            if (getComputedStyle(ch).position === "absolute") continue;
            const r = ch.getBoundingClientRect();
            right = Math.max(right, r.right);
            bottom = Math.max(bottom, r.bottom);
          }
        } else {
          right = box.left + el.scrollWidth;
          bottom = box.top + el.scrollHeight;
        }
        const padR = parseFloat(cs.paddingRight) || 0;
        const padB = parseFloat(cs.paddingBottom) || 0;
        const overR = right - (box.right - padR);
        const overB = bottom - (box.bottom - padB);
        if (overR > TOL || overB > TOL) {
          bad.push(`${el.className || el.tagName}  over-right ${Math.round(Math.max(0, overR))}px, over-bottom ${Math.round(Math.max(0, overB))}px`);
        }
      }
      return bad.slice(0, 4);
    });
    if (clipped.length) {
      console.warn(`  ! slide ${i + 1} clips content — trim copy:`);
      for (const b of clipped) console.warn(`      ${b}`);
    }
    const name = `${String(i + 1).padStart(2, "0")}.png`;
    await page.screenshot({ path: join(outDir, name) });
    files.push(name);
    console.log(`  ${basename(dir)}/out/${name}  [${post.slides[i].type}]`);
  }

  // Contact sheet so the whole carousel can be reviewed in one image.
  const cols = Math.min(total, 4);
  const rows = Math.ceil(total / cols);
  const thumbW = 420;
  const thumbH = Math.round((fmt.h / fmt.w) * thumbW);
  const imgs = files.map((f, i) =>
    `<figure><img src="data:image/png;base64,${readFileSync(join(outDir, f)).toString("base64")}">
     <figcaption>${i + 1}. ${post.slides[i].type}</figcaption></figure>`).join("");
  await page.setViewportSize({ width: cols * (thumbW + 24) + 24, height: rows * (thumbH + 62) + 24 });
  await page.setContent(`<style>
    body{margin:0;background:#eef0f5;padding:12px;display:grid;
      grid-template-columns:repeat(${cols},${thumbW}px);gap:12px;
      font:600 15px system-ui,sans-serif;color:#4a5163}
    figure{margin:0}
    img{width:${thumbW}px;height:${thumbH}px;display:block;border-radius:8px;
      box-shadow:0 3px 12px rgba(0,0,0,.14)}
    figcaption{padding:8px 2px 0}
  </style>${imgs}`);
  await page.screenshot({ path: join(outDir, "contact-sheet.png"), fullPage: true });
  await page.close();

  writeFileSync(
    join(outDir, "MANIFEST.txt"),
    [`${post.id} — ${post.title}`, `topic: ${post.topicId}`, `format: ${post.format || "square"} (${fmt.w}x${fmt.h})`,
     `slides: ${total}`, "", ...files.map((f, i) => `${f}  ${post.slides[i].type}`), ""].join("\n")
  );
  console.log(`  → ${total} slides + contact sheet\n`);
}

await browser.close();
