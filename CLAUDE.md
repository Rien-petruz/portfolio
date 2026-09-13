# CLAUDE.md

## Repo

Peter Kekpe's portfolio site (React 18 + Vite 5, inline styles, no CSS
framework). Source lives in `src/`; `src/App.jsx` is the whole page.

`tools/` holds standalone generators that ship no code to the site.

## Social posts — The NewWine Place

`tools/church-carousel/` turns a teaching from Pst Emmanuel Omini into a
carousel, a self-swiping video, and the copy to post them. Each teaching is one
file in `posts/`; brand, formats and the music bed are shared in `config.json`.
The scripts only render what those files say.

```bash
node tools/church-carousel/render.mjs --post <slug>   # slides -> out/<slug>/
node tools/church-carousel/video.mjs  --post <slug>   # video  -> out/<slug>/carousel.mp4
node tools/church-carousel/copy.mjs   --post <slug>   # copy   -> out/<slug>/post-copy.md
```

A new teaching is a new file in `posts/`, never an edit over the last one.
Give it a `theme` — `night` or `parchment` — and don't run the same theme as
the post before it, so the feed doesn't read as one long block.

**Everything is 1080×1350 (4:5) — the house size, on every platform.** Peter
asked for this specifically over a 9:16 short cut; don't add a vertical format
or offer one again unless he asks.

The video carries the music bed named in `video.audio` in `slides.json` —
Peter supplies the track. It's trimmed to the runtime, normalised to −14 LUFS,
faded both ends and resampled to 48 kHz. With no `audio` block it falls back to
a silent track. Only use music Peter has the rights to; anything lifted from
another upload risks a Content ID claim.

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

**Post the teaching exactly as Peter sends it. Never add a Bible verse, a
scripture slide or a reference he didn't include** — he asked for this
specifically. If a teaching mentions a passage without quoting it, leave it
mentioned.

Beyond that, keep the pastor's words as written, his own grammar included.
Titles, hooks, and CTAs are ours to write; the teaching itself is never
paraphrased.
