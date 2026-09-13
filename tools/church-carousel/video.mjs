// Builds a self-swiping video of the carousel: each slide holds for its own
// `hold` seconds, then slides left as the next one comes in, the way a thumb
// would push it. Run render.mjs first.
//
//   node tools/church-carousel/video.mjs [--format feed|vertical]
//
// With no --format it builds every format in slides.json: the 4:5 feed cut and
// the 9:16 cut for TikTok and YouTube Shorts.
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

const { slides, formats, video } = JSON.parse(readFileSync(join(here, 'slides.json'), 'utf8'));
const { fps = 30, swipe = 0.5, audio } = video ?? {};

const i = process.argv.indexOf('--format');
const only = i > -1 ? process.argv[i + 1] : undefined;
if (only && !formats[only]) {
  throw new Error(`Unknown format "${only}". slides.json has: ${Object.keys(formats).join(', ')}`);
}
const chosen = only ? [[only, formats[only]]] : Object.entries(formats);

const ffmpeg = findFfmpeg();

for (const [name, format] of chosen) {
build(name, format);
}

function build(name, format) {
const frames = slides.map((s, i) => {
  const file = join(here, format.dir, `slide-${String(i + 1).padStart(2, '0')}.png`);
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

const total = frames.reduce((a, f) => a + f.hold, 0) - swipe * (frames.length - 1);

  // A bed of music if slides.json names one, otherwise silence — some
  // platforms reject or mishandle a video with no audio stream at all.
  const track = audio?.file ? join(here, audio.file) : null;
  if (track && !existsSync(track)) throw new Error(`Missing audio ${track}`);

  const fadeIn = audio?.fadeIn ?? 1;
  const fadeOut = audio?.fadeOut ?? 2.5;

  const audioIn = track
    ? ['-ss', String(audio.startAt ?? 0), '-i', track]
    : ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100'];

  // Trim to the slides, normalise to what the platforms re-encode to anyway,
  // then fade both ends so it neither slams in nor cuts off.
  const audioChain = track
    ? `[${frames.length}:a]atrim=duration=${total.toFixed(3)},asetpts=N/SR/TB,`
      + `loudnorm=I=${audio.loudness ?? -14}:TP=-1.5:LRA=11,`
      + `afade=t=in:st=0:d=${fadeIn},`
      + `afade=t=out:st=${(total - fadeOut).toFixed(3)}:d=${fadeOut},`
      // loudnorm runs at its own internal rate — put it back to the 48kHz the
      // platforms expect, or some uploaders reject the file.
      + `aresample=48000[a]`
    : null;

const filter = [
  `${steps.join(';')}`,
  `[v]fps=${fps},scale=${format.width}:${format.height},format=yuv420p[out]`,
  ...(audioChain ? [audioChain] : []),
].join(';');

const dest = join(here, format.dir, format.video);

execFileSync(ffmpeg, [
  '-y', '-loglevel', 'error',
  ...inputs,
  ...audioIn,
  '-filter_complex', filter,
  '-map', '[out]', '-map', audioChain ? '[a]' : `${frames.length}:a`,
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-profile:v', 'high', '-level', '4.0',
  '-c:a', 'aac', '-b:a', track ? '192k' : '96k', '-shortest',
  '-movflags', '+faststart',
  dest,
], { stdio: ['ignore', 'inherit', 'inherit'] });

console.log(`✓ ${name.padEnd(9)} ${format.width}x${format.height}  ${total.toFixed(1)}s  ${(statSync(dest).size / 1024 / 1024).toFixed(1)} MB  ${track ? 'with music' : 'silent'}  → ${join(format.dir, format.video)}`);
}
