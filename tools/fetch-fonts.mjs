// Downloads the brand webfonts into brand/assets/fonts so slide rendering is
// reproducible offline and deterministic. Run once; the files are committed.
// Google serves these families as variable fonts, so one file covers all weights.
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "brand/assets/fonts");
mkdirSync(outDir, { recursive: true });

// A modern-browser UA makes the CSS API serve woff2.
const UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36";

const FAMILIES = [
  { name: "Inter", css: "Inter:wght@400;500;600;700;800;900" },
  { name: "JetBrainsMono", css: "JetBrains+Mono:wght@400;500;700" },
  { name: "Caveat", css: "Caveat:wght@700" },
  { name: "SourceSerif4", css: "Source+Serif+4:opsz,wght@8..60,600;8..60,700" },
];

for (const fam of FAMILIES) {
  const url = `https://fonts.googleapis.com/css2?family=${fam.css}&display=swap`;
  const css = await (await fetch(url, { headers: { "User-Agent": UA } })).text();
  // Latin subset only — the slides are English and the files stay small.
  const latin = css
    .split("@font-face")
    .slice(1)
    .find((b) => /unicode-range:[^;]*U\+0000-00FF/.test(b));
  const src = latin && (latin.match(/url\((https:[^)]+\.woff2)\)/) || [])[1];
  if (!src) { console.error(`${fam.name}: no latin woff2 found`); continue; }

  const file = join(outDir, `${fam.name}.woff2`);
  if (existsSync(file)) { console.log(`${fam.name}: cached`); continue; }
  const buf = Buffer.from(await (await fetch(src, { headers: { "User-Agent": UA } })).arrayBuffer());
  writeFileSync(file, buf);
  console.log(`${fam.name}.woff2  ${(buf.length / 1024).toFixed(0)} KB`);
}
