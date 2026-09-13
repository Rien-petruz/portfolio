// Shared loading for the carousel scripts.

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

// Posts live one-per-file in posts/; brand, formats and video settings are
// shared in config.json.
export function loadPost(here, argv) {
  const i = argv.indexOf('--post');
  const slug = i > -1 ? argv[i + 1] : undefined;

  const dir = join(here, 'posts');
  const slugs = readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => f.replace(/\.json$/, ''));
  if (!slugs.length) throw new Error(`No posts in ${dir}`);

  if (slug && !slugs.includes(slug)) {
    throw new Error(`Unknown post "${slug}". Have: ${slugs.join(', ')}`);
  }
  if (!slug && slugs.length > 1) {
    throw new Error(`Several posts exist — pass --post <slug>. Have: ${slugs.join(', ')}`);
  }

  const name = slug ?? slugs[0];
  const post = JSON.parse(readFileSync(join(dir, `${name}.json`), 'utf8'));
  const config = JSON.parse(readFileSync(join(here, 'config.json'), 'utf8'));
  return { ...config, ...post, slug: post.slug ?? name };
}
