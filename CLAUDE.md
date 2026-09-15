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
Give it a `theme` — `night`, `parchment`, `vintage` or `tempest` — and rotate
it, never repeating the post before. Peter notices when two look alike, so when in doubt
reach for the one he has not seen in a while, or add a new palette to
`template.mjs` (drawn from the logo, so the decks stay a family).

**The deck and the video are 1080×1350 (4:5) — the house size, on every
platform.** Peter asked for this specifically over a 9:16 short cut; don't add
a vertical video format or offer one again unless he asks.

**The thumbnail is the exception: 1080×1920 (9:16), at his request.** It is the
opening slide laid out again at that size — a real render, not a crop or a pad
of the 4:5 slide — and with no footer, since a slide counter and "swipe" belong
on a deck, not on a standalone cover. `thumbnail` in `config.json` sets the
size. Don't "correct" it back to 4:5 or put the footer back.

The video carries the music bed named in `video.audio` in `slides.json` —
Peter supplies the track. It's trimmed to the runtime, normalised to −14 LUFS,
faded both ends and resampled to 48 kHz. With no `audio` block it falls back to
a silent track. Only use music Peter has the rights to; anything lifted from
another upload risks a Content ID claim.

**Every post is delivered as exactly five things:**

1. **The video** — with the music bed, built the same way every time
2. **The thumbnail** — `out/<slug>/thumbnail.png`, the opening slide at 9:16, sent as a file
3. **The title**
4. **The description**
5. **The tags** (hashtags and keywords)

Peter asked for each of these specifically. Apart from the thumbnail, the slide
images are not the deliverable — they are the frames the video is built from,
so render them, build the video, and hand over the video. Don't ship a post
missing any of the five.

**The title, description and tags are one set — the same copy on Facebook,
YouTube, TikTok and Instagram.** Don't write per-platform variants or split
them up again unless he asks.

Because one set has to work everywhere, write to the tightest limit of the
four: the title under 100 chars so YouTube doesn't truncate it, the caption
short, the hashtags no more than 30. Mix in community tags (#BibleTok,
#ChristianTikTok) alongside the branded ones so the single set still travels.

`copy.mjs` checks each field against the binding limit and names the platform
it comes from.

**The description is Peter's text, character for character, and nothing else.**
No byline, no "tell us in the comments", no closing line of ours, and no
spelling or grammar corrections — he asked for this specifically after earlier
posts carried both. If something reads like a typo, leave it and say so in the
reply; he decides.

**Never add a Bible verse, a scripture slide or a reference he didn't
include.** If a teaching mentions a passage without quoting it, leave it
mentioned.

The slides carry his sentences under the same rule. The title, the opening
hook and its sub-line are the only copy that is ours to write.

The teaching itself is never paraphrased, shortened or tidied.

**The title has to carry the moral, not describe the scene.** Peter rejected
"Same Storm. One Panicked, One Slept." for exactly this: it recounted what
happened in the passage instead of the lesson drawn from it. Ask what the
teaching is telling the reader about themselves, then say that in a way that
opens a question — "The Real Storm Wasn't The One They Could See" carries the
moral (the real problem is inside) and still makes you want the answer. A title
that only narrates the story is a miss, however neat it sounds.

The opening slide's headline and the post title should say the same thing, so
the thumbnail and the title agree.
