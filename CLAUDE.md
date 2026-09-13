# CLAUDE.md

## Repo

Peter Kekpe's portfolio site (React 18 + Vite 5, inline styles, no CSS
framework). Source lives in `src/`; `src/App.jsx` is the whole page.

`tools/` holds standalone generators that ship no code to the site.

## Social posts — The NewWine Place

`tools/church-carousel/` turns a teaching from Pst Emmanuel Omini into a
carousel, a self-swiping video, and the copy to post them. Everything for a
post lives in `slides.json`; the scripts only render it.

```bash
node tools/church-carousel/render.mjs    # slides -> out/ (4:5) and out/9x16/
node tools/church-carousel/video.mjs     # videos -> out/carousel.mp4, out/9x16/carousel-9x16.mp4
node tools/church-carousel/copy.mjs      # post copy -> out/post-copy.md, out/copy/*.txt
```

Every post ships in both formats: 1080×1350 for the Instagram and Facebook
feed, 1080×1920 for TikTok and YouTube Shorts. The vertical deck is rendered
natively, never letterboxed from the 4:5 one, and keeps its lower third clear
of the caption and buttons those apps overlay.

Videos ship with a silent audio track for the platforms that need one. Music
goes on in-app, from the platform's own licensed library — never lifted from
someone else's upload.

**Every post ships copy for all four platforms — Facebook, YouTube, TikTok,
Instagram — and each one gets a title, a description, hashtags, and tags.**
Never hand over slides or a video without it.

Write the four platforms separately rather than pasting one caption into all
of them; they reward different things:

| | What works |
|---|---|
| Instagram | Hook in the first line before the "more" cut; up to 30 hashtags; comment-prompt CTA |
| Facebook | Longer narrative, full verse quoted; only a few hashtags; a share prompt |
| YouTube | Title under 100 chars carrying the curiosity; keywords in the tags field; first 3 hashtags show above the title |
| TikTok | Short and punchy; community hashtags (#bibletok, #christiantiktok) over branded ones |

`copy.mjs` checks each platform against its real limits and says what is over.

Keep the pastor's words as written. Titles, hooks, and CTAs are ours to write;
the teaching itself is not paraphrased.
