# Church carousel generator — The NewWine Place

Turns a teaching (scripture + message + pastor's byline) into a set of
ready-to-post carousel slides for **@thenewwineplace**.

## Render

```bash
node tools/church-carousel/render.mjs --post name-your-reality
node tools/church-carousel/render.mjs --post name-your-reality --out ~/Desktop/post
```

Every script takes `--post <slug>`, matching a file in `posts/`, and writes to
`out/<slug>/`.

No install step: the slides are HTML rendered by the Chromium already on the
machine, with the fonts and logo inlined as data URIs so a render never touches
the network.

## Files

| File | Purpose |
|---|---|
| `posts/*.json` | One file per teaching — slides, theme and post copy |
| `config.json` | Brand, formats and the music bed, shared by every post |
| `load.mjs` | Resolves `--post <slug>` and merges it with the config |
| `template.mjs` | Slide markup + the brand styling |
| `render.mjs` | HTML → PNG via headless Chromium |
| `assets/logo.jpg` | Profile mark shown on every slide |
| `assets/audio/` | Music bed muxed into the video |
| `assets/fonts/` | Playfair Display + Inter (latin subsets) |
| `tojpeg.mjs` | PNG → JPEG for uploading or sharing |
| `video.mjs` | Slides → a self-swiping MP4 |
| `copy.mjs` | Post copy for all four platforms |
| `out/` | Rendered slides, `slide-01.png` … (plus `.jpg` copies) |
| `out/<slug>/thumbnail.png` | The opening slide, for use as the video thumbnail |
| `out/carousel.mp4` | The video cut of the deck |
| `out/post-copy.md` | The post copy, with its limit check |
| `out/copy/post.txt` | Paste-ready title, caption, hashtags, tags |

## Format

Everything renders at **1080×1350 (4:5)** — the tallest the feed allows, so a
post takes the most space on screen. This is the house size; use it on every
platform, including TikTok and YouTube, where it posts fine and simply sits
inside a little letterboxing.

`formats` in `config.json` is what defines it. The scripts loop whatever is in
there and take `--format <name>` to build just one, so a second size can be
added later without touching them.

## Video

```bash
npm i ffmpeg-static                          # once
node tools/church-carousel/video.mjs --post name-your-reality
```

Each slide holds for its own `hold` seconds (set per slide in the post's file),
then slides left as the next one arrives — a hands-free version of the swipe.
Output is H.264 1080×1350. The music bed comes from `video.audio` in
`config.json`:

```json
"audio": {
  "file": "assets/audio/prayer-instrumental.mp3",
  "startAt": 0,          // seconds into the track to begin
  "fadeIn": 1.0,
  "fadeOut": 2.5,
  "loudness": -14        // LUFS
}
```

It's trimmed to the slide runtime, normalised to −14 LUFS (what the platforms
re-encode to anyway, so they won't crush it further), faded at both ends, and
resampled to 48 kHz — `loudnorm` runs at its own internal rate and some
uploaders reject what comes out otherwise.

Drop the `audio` block and the video falls back to a silent track, since some
platforms mishandle a video with no audio stream at all.

Use music you have the rights to. Anything lifted from another upload risks a
Content ID claim, which mutes or pulls the post.

Pace the `hold` values by how much there is to read: a full verse needs about
five seconds, a short line about three. Total runtime prints when the render
finishes.

`video.mjs` needs a full ffmpeg — H.264 and the `xfade` filter. The ffmpeg
bundled with Playwright's Chromium has neither (it only decodes MJPEG and
encodes VP8), so install `ffmpeg-static` or point `FFMPEG_PATH` at a real one.

## Post copy

```bash
node tools/church-carousel/copy.mjs --post name-your-reality
```

One title, one short description, one set of hashtags and one set of tags —
posted as-is on Facebook, YouTube, TikTok and Instagram. It lives in the `post` block of the
post's file:

```json
"post": {
  "title": "…",         // YouTube's title field; the hook everywhere else
  "description": "…",   // the caption body — keep it short
  "hashtags": ["#…"],   // appended to the caption by copy.mjs
  "tags": ["…"]         // YouTube's keyword field; search keywords elsewhere
}
```

One set has to clear every platform at once, so `copy.mjs` checks each field
against the tightest limit of the four and names which one binds:

| Field | Limit | Set by |
|---|---|---|
| Title | 100 chars | YouTube's title field |
| Caption | 2200 chars | Instagram and TikTok |
| Hashtags | 30 | Instagram |
| Tags | 500 chars joined | YouTube's keyword field |

Output is `out/post-copy.md` and `out/copy/post.txt`.

## Sharing

`slide-NN.png` is the master. For anywhere that wants a smaller file:

```bash
node tools/church-carousel/tojpeg.mjs 0.82 tools/church-carousel/out/slide-0*.png
```

Quality `0.82` lands around 60-110 KB a slide, which is well above what
Instagram keeps after its own re-compression. The grain texture dominates the
file size, so dropping quality further buys little and costs more than it
saves.

## Writing a post

Add a file to `posts/`. Never edit over the last teaching — each one keeps its
own file and its own `out/<slug>/` folder.

Post the teaching exactly as sent. Don't add a verse, a scripture slide or a
reference that wasn't in it.

Pick a `theme` and alternate it from the post before, so consecutive posts
don't look identical in the feed:

| Theme | Look |
|---|---|
| `night` | Near-black, the logo's purple and red glowing in at the corners, gold accents |
| `parchment` | Warm bone paper, plum ink, the logo's purple carrying the emphasis |
| `vintage` | Deep wine, crimson and purple at the corners, warm gold emphasis |

Every palette is drawn from the logo, so the decks stay a family. Themes are
defined in `template.mjs` — add another there when these three start repeating.

Copy conventions:

- `*word*` wraps a phrase in the gold italic highlight.
- `\n` is a line break, `\n\n` a new paragraph.
- Slide 1 should be a curiosity hook; the last slide carries the pastor's name.

Slide types:

| `type` | Fields | Use for |
|---|---|---|
| `hook` | `eyebrow`, `title`, `sub`, `cue` | Opening slide |
| `verse` | `eyebrow`, `verse`, `ref` | Scripture |
| `statement` | `kicker`, `lead`, `body` | Teaching beats |
| `quote` | `eyebrow`, `quote` | The one line to screenshot |
| `closing` | `title`, `author`, `church`, `cta` | Byline + call to action |

Keep the deck to 10 slides or fewer — that is Instagram's carousel limit.

## Environment note

`render.mjs` prefers Chromium's `headless_shell` binary. The full `chrome`
binary reserves ~87px of window chrome, which makes `--window-size` produce a
short viewport and clips the slide footer; `CHROME_PATH` overrides the search
if neither is where the script looks.
