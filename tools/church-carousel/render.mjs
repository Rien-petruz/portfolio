// Renders slides.json into ready-to-post PNGs using the Chromium that ships
// with this environment. Fonts and the logo are inlined as data URIs so a
// render never depends on the network.
//
//   node tools/church-carousel/render.mjs [--format feed|vertical] [--out <dir>]
//
// With no --format it renders every format in slides.json: the 4:5 feed deck
// and the 9:16 cut for TikTok and YouTube Shorts.

import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderSlide } from './template.mjs';

const here = dirname(fileURLToPath(import.meta.url));

// headless_shell first: the full browser reserves ~87px of window chrome, so
// --window-size there yields a short viewport and clips the slide footer.
const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell',
  '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  '/usr/bin/chromium',
  '/usr/bin/google-chrome',
].filter(Boolean);

function findChrome() {
  const found = CHROME_CANDIDATES.find((p) => existsSync(p));
  if (found) return found;
  throw new Error(`No Chromium found. Set CHROME_PATH. Tried:\n  ${CHROME_CANDIDATES.join('\n  ')}`);
}

const dataUri = (file, mime) =>
  `data:${mime};base64,${readFileSync(join(here, file)).toString('base64')}`;

const flag = (name) => {
  const i = process.argv.indexOf(name);
  return i > -1 ? process.argv[i + 1] : undefined;
};

const config = JSON.parse(readFileSync(join(here, 'slides.json'), 'utf8'));
const { brand, slides, formats } = config;

const only = flag('--format');
if (only && !formats[only]) {
  throw new Error(`Unknown format "${only}". slides.json has: ${Object.keys(formats).join(', ')}`);
}
const chosen = only ? [[only, formats[only]]] : Object.entries(formats);

const fonts = {
  inter: dataUri('assets/fonts/Inter-var.woff2', 'font/woff2'),
  playfair: dataUri('assets/fonts/PlayfairDisplay-var.woff2', 'font/woff2'),
  playfairItalic: dataUri('assets/fonts/PlayfairDisplay-var-italic.woff2', 'font/woff2'),
};
const avatar = dataUri(brand.avatar, 'image/jpeg');

const chrome = findChrome();

for (const [name, format] of chosen) {
  const outDir = resolve(here, flag('--out') ?? format.dir);
  const workDir = join(outDir, '.html');

  rmSync(workDir, { recursive: true, force: true });
  mkdirSync(workDir, { recursive: true });

  slides.forEach((slide, i) => {
    const n = String(i + 1).padStart(2, '0');
    const html = join(workDir, `slide-${n}.html`);
    const png = join(outDir, `slide-${n}.png`);

    writeFileSync(html, renderSlide({ slide, index: i, total: slides.length, brand, avatar, fonts, format }));

    execFileSync(chrome, [
      ...(chrome.endsWith('headless_shell') ? [] : ['--headless=new']),
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
      '--force-device-scale-factor=1',
      '--virtual-time-budget=3000',
      `--window-size=${format.width},${format.height}`,
      `--screenshot=${png}`,
      `file://${html}`,
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
  });

  rmSync(workDir, { recursive: true, force: true });
  console.log(`✓ ${name.padEnd(9)} ${format.width}x${format.height}  ${slides.length} slides → ${outDir}`);
}
