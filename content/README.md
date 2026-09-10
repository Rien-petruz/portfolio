# Backend Engineering content series

A daily technical posting pipeline: 328 topics from the master list, studied
in depth, then rendered into branded carousel slides for LinkedIn, Instagram,
Facebook and TikTok.

**Nothing gets designed before it has been studied.** See
`content/research/README.md` for the standard and why it exists.

## What's here

```
content/
  master-list.md              328 topics, 18 sections (human-readable)
  topics.json                 the same list as data, with per-topic status
  research/
    README.md                 the research standard — read this first
    TEMPLATE.md               brief skeleton
    T0XX-<slug>/brief.md      the study
    T0XX-<slug>/experiment/   runnable proof of the claims
  posts/<id>-<slug>/
    slides.json               slide definitions for one carousel
    post.md                   caption copy + formula check
    out/                      per-platform renders (see below)
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

## Output, per post

```
out/
  portrait/01.png … NN.png   1080x1350  LinkedIn · Instagram · Facebook
  story/01.png … NN.png      1080x1920  TikTok (bottom 470px kept clear of its UI)
  linkedin.pdf               LinkedIn carousels post as a PDF document
  portrait.zip / story.zip   grab-and-go
  <format>/contact-sheet.png review aid — NOT for posting
```

Every numbered PNG is standalone: one file, one slide, upload as-is. The zips
are a convenience, not a different artifact.

| Platform | Format | Notes |
|---|---|---|
| LinkedIn | 1080x1350 + PDF | carousels are document posts; PNGs also provided |
| Instagram | 1080x1350 | carousel, up to 20 images |
| Facebook | 1080x1350 | carousel |
| TikTok | 1080x1920 | photo carousel, up to 35 images |

## The daily loop

```bash
node tools/status.mjs                       # what's next in the queue
node tools/status.mjs T0XX researching      # claim it

# 1. STUDY — write content/research/T0XX-<slug>/brief.md against the standard,
#    with a runnable experiment where a claim can be measured.
node tools/status.mjs T0XX researched

# 2. DESIGN — only now
mkdir -p content/posts/00N-<slug>           # slides.json + post.md
node tools/render.mjs content/posts/00N-<slug>
node tools/status.mjs T0XX drafted 00N-<slug>

# 3. PUBLISH
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
