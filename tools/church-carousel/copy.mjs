// Builds the post copy from the `post` block in slides.json — one title, one
// description, one set of hashtags and tags, used on every platform.
//
//   node tools/church-carousel/copy.mjs
//
// Writes out/post-copy.md and out/copy/post.txt. Because one set has to work
// everywhere, each field is checked against the tightest limit among Facebook,
// YouTube, TikTok and Instagram, and the report names which one binds.

import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

// The binding limit for each field, and the platform it comes from.
const LIMITS = {
  title: { max: 100, from: 'YouTube title' },
  caption: { max: 2200, from: 'Instagram and TikTok captions' },
  hashtags: { max: 30, from: 'Instagram' },
  tagsChars: { max: 500, from: "YouTube's keyword field" },
};

const { post } = JSON.parse(readFileSync(join(here, 'slides.json'), 'utf8'));
if (!post) throw new Error('slides.json has no `post` block.');

const { title, description, hashtags, tags } = post;
const caption = `${description}\n\n${hashtags.join(' ')}`;
const tagLine = tags.join(', ');

const rows = [
  ['Title', title.length, LIMITS.title],
  ['Caption', caption.length, LIMITS.caption],
  ['Hashtags', hashtags.length, LIMITS.hashtags],
  ['Tags', tagLine.length, LIMITS.tagsChars],
];

const over = rows.filter(([, n, lim]) => n > lim.max);

const outDir = join(here, 'out');
const copyDir = join(outDir, 'copy');
rmSync(copyDir, { recursive: true, force: true });
mkdirSync(copyDir, { recursive: true });

writeFileSync(join(copyDir, 'post.txt'), [
  '=== THE NEWWINE PLACE — POST COPY ===',
  'One set for Facebook, YouTube, TikTok and Instagram.',
  '',
  '--- TITLE ---',
  title,
  '',
  '--- DESCRIPTION / CAPTION ---',
  caption,
  '',
  '--- HASHTAGS ---',
  hashtags.join(' '),
  '',
  '--- TAGS / KEYWORDS ---',
  tagLine,
  '',
].join('\n'));

writeFileSync(join(outDir, 'post-copy.md'), [
  `# Post copy — ${post.slug}`,
  '',
  `Scripture: ${post.scripture}. One set, posted as-is on Facebook, YouTube, TikTok and Instagram.`,
  '',
  `## Title (${title.length} chars)`,
  '',
  `> ${title}`,
  '',
  `## Description (${description.length} chars)`,
  '',
  '```',
  description,
  '```',
  '',
  `## Hashtags (${hashtags.length})`,
  '',
  hashtags.join(' '),
  '',
  '## Tags / keywords',
  '',
  tagLine,
  '',
  '## Fits everywhere',
  '',
  '| Field | Length | Limit | Set by |',
  '|---|---|---|---|',
  ...rows.map(([name, n, lim]) => `| ${name} | ${n} | ${lim.max} | ${lim.from} |`),
  '',
].join('\n'));

for (const [name, n, lim] of rows) {
  const mark = n > lim.max ? '!' : '✓';
  console.log(`${mark} ${name.padEnd(9)} ${String(n).padStart(4)} / ${String(lim.max).padEnd(4)}  (${lim.from})`);
}

console.log(over.length
  ? `\n${over.length} field(s) over — trim before posting.`
  : '\nOne set, fits every platform.');
console.log(`\npost-copy.md + copy/post.txt → ${outDir}`);
