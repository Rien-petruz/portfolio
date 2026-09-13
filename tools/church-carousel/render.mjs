// Renders slides.json into ready-to-post PNGs using the Chromium that ships
// with this environment. Fonts and the logo are inlined as data URIs so a
// render never depends on the network.
//
//   node tools/church-carousel/render.mjs [--out <dir>]

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

const outFlag = process.argv.indexOf('--out');
const outDir = resolve(here, outFlag > -1 ? process.argv[outFlag + 1] : 'out');
const workDir = join(outDir, '.html');

const config = JSON.parse(readFileSync(join(here, 'slides.json'), 'utf8'));
const { brand, slides, size } = config;

const fonts = {
  inter: dataUri('assets/fonts/Inter-var.woff2', 'font/woff2'),
  playfair: dataUri('assets/fonts/PlayfairDisplay-var.woff2', 'font/woff2'),
  playfairItalic: dataUri('assets/fonts/PlayfairDisplay-var-italic.woff2', 'font/woff2'),
};
const avatar = dataUri(brand.avatar, 'image/jpeg');

rmSync(workDir, { recursive: true, force: true });
mkdirSync(workDir, { recursive: true });

const chrome = findChrome();

slides.forEach((slide, i) => {
  const n = String(i + 1).padStart(2, '0');
  const html = join(workDir, `slide-${n}.html`);
  const png = join(outDir, `slide-${n}.png`);

  writeFileSync(html, renderSlide({ slide, index: i, total: slides.length, brand, avatar, fonts }));

  execFileSync(chrome, [
    ...(chrome.endsWith('headless_shell') ? [] : ['--headless=new']),
    '--no-sandbox',
    '--disable-gpu',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    '--virtual-time-budget=3000',
    `--window-size=${size.width},${size.height}`,
    `--screenshot=${png}`,
    `file://${html}`,
  ], { stdio: ['ignore', 'ignore', 'pipe'] });

  console.log(`✓ slide-${n}.png  (${slide.type})`);
});

rmSync(workDir, { recursive: true, force: true });
console.log(`\n${slides.length} slides → ${outDir}`);
