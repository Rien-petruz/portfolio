# Repository guide

Two things live here:

1. **The portfolio site** at `src/` (React 18 + Vite, single `App.jsx`).
2. **A daily technical content pipeline** at `content/`, `brand/` and `tools/`,
   which produces carousel posts for LinkedIn, Instagram, Facebook and TikTok.

Most work is on the content pipeline. Start at `content/README.md`.

## Non negotiables for content work

- **Read `content/STYLE.md` before writing any copy.** The headline rule: no
  dashes anywhere in published copy, titles must be catchy and curious, and all
  tags go in one combined block used on every platform.
- **Study before designing.** Nothing gets a carousel until it has a brief in
  `content/research/`. See `content/research/README.md` for the standard and
  for why it exists. A draft carousel already shipped one measured bug because
  this step was skipped.
- **Numbers come from experiments**, not from articles. There is a real
  PostgreSQL, Redis, gcc, strace and `/proc` in this container. Use them.
- **The author footer is rendered by the template** on every slide. It is not a
  per slide option.

## Common commands

```bash
node tools/status.mjs                       # the content queue
node tools/status.mjs --stats               # progress across 18 sections
node tools/lint-copy.mjs <postDir>          # style check before rendering
node tools/render.mjs <postDir>             # slides.json to PNG, PDF and zips
node tools/render.mjs --all
npm run dev                                 # the portfolio site
```

Scratch PostgreSQL for experiments, once per container:

```bash
sudo -u postgres /usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/labdata -U postgres --auth=trust
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/labdata \
  -o '-p 5433 -k /tmp' -l /var/lib/postgresql/pg.log start
```

## Author

Peter Kekpe, `@peter-kekpe`. Brand tokens and the headshot are in `brand/`.
