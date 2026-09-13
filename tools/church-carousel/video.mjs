// Builds a self-swiping video of the carousel: each slide holds for its own
// `hold` seconds, then slides left as the next one comes in, the way a thumb
// would push it. Run render.mjs first.
//
//   node tools/church-carousel/video.mjs
//
// Needs a full ffmpeg (H.264 + the xfade filter). It looks for $FFMPEG_PATH,
// then an ffmpeg-static install, then ffmpeg on PATH. The Chromium that ships
// with Playwright bundles an ffmpeg too, but that build has neither.

import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function findFfmpeg() {
  if (process.env.FFMPEG_PATH) return process.env.FFMPEG_PATH;
  try {
    const p = require('ffmpeg-static');
    if (p && existsSync(p)) return p;
  } catch { /* not installed */ }
  try {
    return execFileSync('which', ['ffmpeg'], { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
  } catch {
    throw new Error('No ffmpeg with H.264 + xfade found. Install one: npm i ffmpeg-static, or set FFMPEG_PATH.');
  }
}

const { slides, size, video } = JSON.parse(readFileSync(join(here, 'slides.json'), 'utf8'));
const { fps = 30, swipe = 0.5, output = 'carousel.mp4' } = video ?? {};

const frames = slides.map((s, i) => {
  const file = join(here, 'out', `slide-${String(i + 1).padStart(2, '0')}.png`);
  if (!existsSync(file)) throw new Error(`Missing ${file} — run render.mjs first.`);
  return { file, hold: s.hold ?? 3.5, type: s.type };
});

// Each input runs for its own hold. xfade consumes `swipe` seconds of overlap
// per transition, so the offset of transition k is the running total of the
// holds so far, less the overlap already spent.
const inputs = frames.flatMap((f) => ['-loop', '1', '-t', String(f.hold), '-i', f.file]);

const steps = [];
let prev = '[0:v]';
let elapsed = 0;

frames.slice(1).forEach((f, i) => {
  elapsed += frames[i].hold;
  const offset = (elapsed - swipe * (i + 1)).toFixed(3);
  const out = i === frames.length - 2 ? '[v]' : `[x${i}]`;
  steps.push(`${prev}[${i + 1}:v]xfade=transition=slideleft:duration=${swipe}:offset=${offset}${out}`);
  prev = out;
});

const filter = [
  `${steps.join(';')}`,
  `[v]fps=${fps},scale=${size.width}:${size.height},format=yuv420p[out]`,
].join(';');

const total = frames.reduce((a, f) => a + f.hold, 0) - swipe * (frames.length - 1);
const dest = join(here, 'out', output);

execFileSync(findFfmpeg(), [
  '-y', '-loglevel', 'error',
  ...inputs,
  // A silent track: some platforms reject or mishandle a video with no audio.
  '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
  '-filter_complex', filter,
  '-map', '[out]', '-map', `${frames.length}:a`,
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-profile:v', 'high', '-level', '4.0',
  '-c:a', 'aac', '-b:a', '96k', '-shortest',
  '-movflags', '+faststart',
  dest,
], { stdio: ['ignore', 'inherit', 'inherit'] });

console.log(`${output}  ${total.toFixed(1)}s  ${(statSync(dest).size / 1024 / 1024).toFixed(1)} MB  ${size.width}x${size.height}`);
