// Renders a post's slides.json into standalone, ready-to-post carousel images.
//
//   node tools/render.mjs content/posts/001-idempotency
//   node tools/render.mjs --all
//   node tools/render.mjs <postDir> --format portrait
//
// Output, per post:
//   out/portrait/01.png … NN.png   LinkedIn · Instagram · Facebook  (1080x1350)
//   out/story/01.png … NN.png      TikTok                           (1080x1920)
//   out/linkedin.pdf               LinkedIn carousels post as a PDF document
//   out/portrait.zip, out/story.zip
//   out/<format>/contact-sheet.png review aid — not for posting
//
// Every numbered PNG is standalone: one file, one slide, post it as-is.
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
import { readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, basename } from "node:path";
import { assets, css, slideHTML } from "./templates.mjs";

const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const brand = JSON.parse(readFileSync(join(root, "brand/brand.json"), "utf8"));
const a = assets(root, brand);

const argv = process.argv.slice(2);
const flag = (name) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? null : argv[i + 1];
};
const postsRoot = join(root, "content/posts");
const dirs = argv.includes("--all")
  ? readdirSync(postsRoot)
      .filter((d) => existsSync(join(postsRoot, d, "slides.json")))
      .sort()
      .map((d) => join(postsRoot, d))
  : argv.filter((x) => !x.startsWith("--") && !Object.values({ f: flag("format") }).includes(x))
      .map((p) => resolve(p));

if (!dirs.length) {
  console.error("usage: node tools/render.mjs <postDir> [...] | --all  [--format <name>]");
  process.exit(1);
}

/** Which platforms ship from a given format. */
const platformsFor = (fmtName) =>
  Object.entries(brand.platforms)
    .filter(([, p]) => p.format === fmtName)
    .map(([name]) => name);

/** Shrink code and card bodies so nothing is ever silently clipped. */
async function autoFit(page) {
  const code = await page.evaluate(() => {
    const out = [];
    const slideOf = (el) => [...document.querySelectorAll(".slide")].indexOf(el.closest(".slide"));
    document.querySelectorAll(".codewin pre").forEach((pre) => {
      const i = slideOf(pre);
      const el = pre.querySelector("code");
      const start = parseFloat(getComputedStyle(el).fontSize);
      let size = start;
      const fits = () =>
        pre.scrollHeight <= pre.clientHeight + 1 && pre.scrollWidth <= pre.clientWidth + 1;
      while (size > 15 && !fits()) { size -= 0.5; el.style.fontSize = `${size}px`; }
      if (size !== start) out.push({ i, from: start, to: size, ok: fits() });
    });
    return out;
  });

  // Binary search: shrinking widens the compensated box and re-wraps the text,
  // so a first-guess ratio always overshoots.
  const cards = await page.evaluate(() => {
    const out = [];
    const slideOf = (el) => [...document.querySelectorAll(".slide")].indexOf(el.closest(".slide"));
    document.querySelectorAll(".win-body").forEach((body) => {
      const i = slideOf(body);
      const fit = body.querySelector(".win-fit");
      if (!fit) return;
      const padB = parseFloat(getComputedStyle(body).paddingBottom) || 0;
      const fits = (k) => {
        fit.style.transform = k === 1 ? "" : `scale(${k})`;
        fit.style.width = k === 1 ? "100%" : `${100 / k}%`;
        const room = body.getBoundingClientRect().bottom - padB - fit.getBoundingClientRect().top;
        return fit.getBoundingClientRect().height <= room + 1;
      };
      if (fits(1)) return;
      let lo = 0.6, hi = 1, best = 0.6;
      for (let n = 0; n < 14; n++) {
        const mid = (lo + hi) / 2;
        if (fits(mid)) { best = mid; lo = mid; } else hi = mid;
      }
      fits(best);
      out.push({ i, k: best });
    });
    return out;
  });

  return { code, cards };
}

/** Walk the tree and report anything still clipped, using visual bounds. */
async function findClipped(page) {
  return page.evaluate(() => {
    const TOL = 2;
    const report = [];
    document.querySelectorAll(".slide").forEach((slide, i) => {
      for (const el of [slide, ...slide.querySelectorAll("*")]) {
        const cs = getComputedStyle(el);
        if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
        const box = el.getBoundingClientRect();
        const flow = [...el.children].filter((ch) => getComputedStyle(ch).position !== "absolute");
        let right, bottom;
        if (flow.length) {
          right = Math.max(...flow.map((ch) => ch.getBoundingClientRect().right));
          bottom = Math.max(...flow.map((ch) => ch.getBoundingClientRect().bottom));
        } else {
          right = box.left + el.scrollWidth;
          bottom = box.top + el.scrollHeight;
        }
        const overR = right - (box.right - (parseFloat(cs.paddingRight) || 0));
        const overB = bottom - (box.bottom - (parseFloat(cs.paddingBottom) || 0));
        if (overR > TOL || overB > TOL) {
          report.push({ slide: i + 1, el: el.className || el.tagName,
            right: Math.round(Math.max(0, overR)), bottom: Math.round(Math.max(0, overB)) });
        }
      }
    });
    return report;
  });
}

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });

for (const dir of dirs) {
  const post = JSON.parse(readFileSync(join(dir, "slides.json"), "utf8"));
  const only = flag("format");
  const formats = only ? [only] : post.formats || brand.defaultFormats;
  const outRoot = join(dir, "out");
  rmSync(outRoot, { recursive: true, force: true });
  mkdirSync(outRoot, { recursive: true });

  const total = post.slides.length;
  const manifest = [`${post.id} — ${post.title}`, `topic: ${post.topicId}`, `slides: ${total}`, ""];
  console.log(`\n${basename(dir)} — ${total} slides`);

  for (const fmtName of formats) {
    const fmt = brand.formats[fmtName];
    if (!fmt) throw new Error(`unknown format "${fmtName}"`);
    const fmtDir = join(outRoot, fmtName);
    mkdirSync(fmtDir, { recursive: true });

    const page = await browser.newPage({ viewport: { width: fmt.w, height: fmt.h } });
    const bodies = post.slides
      .map((s, i) =>
        slideHTML(s, {
          brand, a,
          ctx: { n: i + 1, total, series: post.series || brand.series, last: i === total - 1 },
        })
      )
      .join("\n");
    await page.setContent(`<style>${css(brand, a, fmt)}</style>${bodies}`, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);

    const { code, cards } = await autoFit(page);
    const clipped = await findClipped(page);

    const files = [];
    const slides = page.locator(".slide");
    for (let i = 0; i < total; i++) {
      const name = `${String(i + 1).padStart(2, "0")}.png`;
      await slides.nth(i).screenshot({ path: join(fmtDir, name) });
      files.push(name);
    }

    const users = platformsFor(fmtName);
    console.log(`  ${fmtName} ${fmt.w}x${fmt.h}  →  ${users.join(", ") || "(no platform)"}`);
    for (const c of code) {
      console.log(`    slide ${c.i + 1}: code ${c.from}px → ${c.to}px${c.ok ? "" : "  ! still clipped"}`);
    }
    for (const c of cards) console.log(`    slide ${c.i + 1}: card scale ${c.k.toFixed(3)}`);
    for (const c of clipped) {
      console.warn(`    ! slide ${c.slide} clips (${c.el}) right +${c.right} bottom +${c.bottom} — trim copy`);
    }

    // Contact sheet — a review aid, never for posting.
    const cols = Math.min(total, 4);
    const thumbW = 400;
    const thumbH = Math.round((fmt.h / fmt.w) * thumbW);
    const cells = files.map((f, i) =>
      `<figure><img src="data:image/png;base64,${readFileSync(join(fmtDir, f)).toString("base64")}">
       <figcaption>${i + 1}. ${post.slides[i].type}</figcaption></figure>`).join("");
    const sheet = await browser.newPage();
    await sheet.setContent(`<style>
      body{margin:0;background:#eef0f5;padding:12px;display:grid;
        grid-template-columns:repeat(${cols},${thumbW}px);gap:12px;
        font:600 15px system-ui,sans-serif;color:#4a5163}
      figure{margin:0}
      img{width:${thumbW}px;height:${thumbH}px;display:block;border-radius:8px;
        box-shadow:0 3px 12px rgba(0,0,0,.14)}
      figcaption{padding:8px 2px 0}
    </style>${cells}`);
    await sheet.screenshot({ path: join(fmtDir, "contact-sheet.png"), fullPage: true });
    await sheet.close();

    // LinkedIn wants the carousel as a PDF document post.
    if (users.includes("linkedin")) {
      await page.emulateMedia({ media: "print" });
      await page.pdf({
        path: join(outRoot, "linkedin.pdf"),
        width: `${fmt.w}px`, height: `${fmt.h}px`,
        printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 },
      });
      await page.emulateMedia({ media: "screen" });
      console.log(`    linkedin.pdf (${total} pages)`);
    }
    await page.close();

    execFileSync("zip", ["-q", "-r", "-j", join(outRoot, `${fmtName}.zip`),
      ...files.map((f) => join(fmtDir, f))]);

    manifest.push(
      `${fmtName}  ${fmt.w}x${fmt.h}  →  ${users.join(", ")}`,
      `  ${fmt.use}`,
      ...files.map((f, i) => `  ${fmtName}/${f}  ${post.slides[i].type}`),
      `  ${fmtName}.zip`,
      ""
    );
  }

  if (formats.some((f) => platformsFor(f).includes("linkedin"))) {
    manifest.push("linkedin.pdf  — upload as a LinkedIn document post", "");
  }
  manifest.push("contact-sheet.png in each format folder is a review aid, not for posting.", "");
  writeFileSync(join(outRoot, "MANIFEST.txt"), manifest.join("\n"));
}

await browser.close();
console.log("");
