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

**Every post ships one title, one short description, one set of hashtags and
one set of tags — the same copy on Facebook, YouTube, TikTok and Instagram.**
Peter asked for this specifically; do not write per-platform variants or split
them up again unless he asks. Never hand over slides or a video without it.

Because one set has to work everywhere, write to the tightest limit of the
four: the title under 100 chars so YouTube doesn't truncate it, the caption
short, the hashtags no more than 30. Mix in community tags (#BibleTok,
#ChristianTikTok) alongside the branded ones so the single set still travels.

`copy.mjs` checks each field against the binding limit and names the platform
it comes from.

Keep the pastor's words as written. Titles, hooks, and CTAs are ours to write;
the teaching itself is not paraphrased.
