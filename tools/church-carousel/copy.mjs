// Builds the post copy for every platform from the `post` block in
// slides.json, and checks it against each platform's real limits.
//
//   node tools/church-carousel/copy.mjs
//
// Writes out/post-copy.md (everything in one place) and out/copy/<platform>.txt
// (one file per platform, split by which field each part goes in).

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

const PLATFORMS = {
  instagram: {
    label: 'Instagram',
    // The caption box holds the description and the hashtags together.
    caption: (p) => `${p.description}\n\n.\n.\n.\n${p.hashtags.join(' ')}`,
    limits: { caption: 2200, hashtags: 30 },
    fields: 'Caption = description + hashtags. Tags are accounts you tag on the image itself.',
  },
  facebook: {
    label: 'Facebook',
    caption: (p) => `${p.description}\n\n${p.hashtags.join(' ')}`,
    limits: { caption: 63206, hashtags: 6 },
    fields: 'Post body = description + hashtags. Facebook rewards fewer hashtags than Instagram.',
  },
  youtube: {
    label: 'YouTube',
    caption: (p) => p.description,
    limits: { title: 100, caption: 5000, tagsChars: 500 },
    fields: 'Title and description are separate fields. Tags go in the keywords field; the first 3 hashtags show above the title.',
  },
  tiktok: {
    label: 'TikTok',
    caption: (p) => `${p.description}\n\n${p.hashtags.join(' ')}`,
    limits: { caption: 2200, hashtags: 10 },
    fields: 'Caption = description + hashtags. Tags are search keywords, not a field you fill in.',
  },
};

const { post } = JSON.parse(readFileSync(join(here, 'slides.json'), 'utf8'));
if (!post) throw new Error('slides.json has no `post` block — add one before running copy.mjs.');

const outDir = join(here, 'out');
const copyDir = join(outDir, 'copy');
mkdirSync(copyDir, { recursive: true });

const warnings = [];

function check(name, spec, p, caption) {
  const { limits } = spec;
  const flag = (cond, msg) => { if (cond) warnings.push(`${spec.label}: ${msg}`); };

  if (limits.title) flag(p.title.length > limits.title,
    `title is ${p.title.length} chars, over the ${limits.title} limit`);
  if (limits.caption) flag(caption.length > limits.caption,
    `caption is ${caption.length} chars, over the ${limits.caption} limit`);
  if (limits.hashtags) flag(p.hashtags.length > limits.hashtags,
    `${p.hashtags.length} hashtags, over the ${limits.hashtags} limit`);
  if (limits.tagsChars) {
    const n = p.tags.join(',').length;
    flag(n > limits.tagsChars, `tags total ${n} chars, over the ${limits.tagsChars} limit`);
  }
}

const sections = [];

for (const [key, spec] of Object.entries(PLATFORMS)) {
  const p = post[key];
  if (!p) { warnings.push(`${spec.label}: no copy in slides.json`); continue; }

  const caption = spec.caption(p);
  check(key, spec, p, caption);

  writeFileSync(join(copyDir, `${key}.txt`), [
    `=== ${spec.label.toUpperCase()} ===`,
    spec.fields,
    '',
    '--- TITLE ---',
    p.title,
    '',
    '--- CAPTION / DESCRIPTION ---',
    caption,
    '',
    '--- HASHTAGS ---',
    p.hashtags.join(' '),
    '',
    '--- TAGS / KEYWORDS ---',
    p.tags.join(', '),
    '',
  ].join('\n'));

  sections.push([
    `## ${spec.label}`,
    '',
    `*${spec.fields}*`,
    '',
    `**Title** (${p.title.length} chars)`,
    '',
    `> ${p.title}`,
    '',
    `**Caption** (${caption.length} chars)`,
    '',
    '```',
    caption,
    '```',
    '',
    `**Hashtags** (${p.hashtags.length})`,
    '',
    p.hashtags.join(' '),
    '',
    '**Tags / keywords**',
    '',
    p.tags.join(', '),
    '',
  ].join('\n'));

  console.log(`✓ ${spec.label.padEnd(10)} title ${String(p.title.length).padStart(3)}  caption ${String(caption.length).padStart(4)}  ${p.hashtags.length} hashtags  ${p.tags.length} tags`);
}

writeFileSync(join(outDir, 'post-copy.md'), [
  `# Post copy — ${post.slug}`,
  '',
  `Scripture: ${post.scripture}. Generated from \`slides.json\`.`,
  '',
  ...sections,
].join('\n'));

if (warnings.length) {
  console.log('\nCheck these:');
  for (const w of warnings) console.log(`  ! ${w}`);
} else {
  console.log('\nEvery platform is within its limits.');
}
console.log(`\npost-copy.md + copy/*.txt → ${outDir}`);
