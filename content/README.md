# Backend Engineering content series

A daily technical posting pipeline: 328 topics from the master list, rendered
into branded carousel slides as PNGs.

## What's here

```
content/
  master-list.md              328 topics, 18 sections (human-readable)
  topics.json                 the same list as data, with posting status
  posts/<id>-<slug>/
    slides.json               slide definitions for one carousel
    post.md                   caption copy + formula check
    out/                      rendered PNGs + contact-sheet.png
brand/
  brand.json                  colours, fonts, author identity
  assets/avatar.png           headshot, cropped from the reference art
  assets/fonts/               Inter, JetBrains Mono, Caveat, Source Serif 4
tools/
  build-topics.mjs            rebuilds the topic bank from the source docx
  status.mjs                  the daily queue driver
  render.mjs                  slides.json -> PNG
  templates.mjs               the four slide themes
  icons.mjs / highlight.mjs   line-art icons, code syntax highlighting
```

## The daily loop

```bash
node tools/status.mjs                       # what's next in the queue
mkdir -p content/posts/002-<slug>           # write slides.json + post.md
node tools/render.mjs content/posts/002-<slug>
node tools/status.mjs T0XX drafted 002-<slug>
# ...after publishing:
node tools/status.mjs T0XX posted
```

`node tools/status.mjs --stats` shows progress across all 18 sections.

## Slide types

| Type | Theme | Use it for |
|---|---|---|
| `cover` | signature — white/lavender, navy accent, big line icon | the hook slide |
| `statement` | marker — white, yellow highlighter, gold index | one blunt claim |
| `concept` | console — browser window, blue kicker | explaining the mechanism |
| `flow` | blueprint — cream, serif numeral, boxed diagram | architecture and data flow |
| `compare` | console | wrong way vs right way |
| `code` | console — dark title bar, syntax highlighted | the actual implementation |
| `takeaway` | ink — dark, closing line + CTA | the one lesson |

Every slide renders the headshot, name and handle in the footer. That is
enforced by the template, not set per slide.

## Copy markup

Inside any headline, sub, desc or note:

- `*accent*` — navy (or blue on dark slides)
- `**bold**`
- `==highlight==` — marker yellow, or lavender on the signature theme
- `` `code` `` — inline mono chip
- `\n` — a real line break (headlines and subs honour it)

## Copy budget

The renderer refuses to clip silently. On every render it:

1. auto-fits code listings by shrinking type until they fit both axes,
2. auto-scales card bodies with a binary search (reported as `card auto-fit scale`),
3. walks the whole element tree and warns on anything still clipped.

An auto-fit scale below ~0.85, or code fitted under ~24px, means the copy is
over budget for that layout — trim the words rather than accepting small type.

## Reproducing the brand assets

```bash
node tools/fetch-fonts.mjs     # re-download the webfonts
node tools/extract-avatar.mjs  # re-crop the headshot from the reference art
node tools/build-topics.mjs    # rebuild the topic bank (posting status is preserved)
```

Brand colours were sampled from `tools/source/reference-cover.png` rather than
eyeballed — navy `#001060`, lavender `#e0e0f0`.
