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
node tools/church-carousel/render.mjs    # slides -> out/slide-NN.png
node tools/church-carousel/video.mjs     # video  -> out/carousel.mp4
node tools/church-carousel/copy.mjs      # post copy -> out/post-copy.md, out/copy/*.txt
```

**Everything is 1080×1350 (4:5) — the house size, on every platform.** Peter
asked for this specifically over a 9:16 short cut; don't add a vertical format
or offer one again unless he asks.

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
