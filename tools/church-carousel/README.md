# Church carousel generator — The NewWine Place

Turns a teaching (scripture + message + pastor's byline) into a set of
ready-to-post carousel slides for **@thenewwineplace**.

## Render

```bash
node tools/church-carousel/render.mjs            # writes tools/church-carousel/out/
node tools/church-carousel/render.mjs --out ~/Desktop/post
```

No install step: the slides are HTML rendered by the Chromium already on the
machine, with the fonts and logo inlined as data URIs so a render never touches
the network.

## Files

| File | Purpose |
|---|---|
| `slides.json` | All copy — edit this to write a new post |
| `template.mjs` | Slide markup + the brand styling |
| `render.mjs` | HTML → PNG via headless Chromium |
| `caption.md` | Caption + hashtags for the post body |
| `assets/logo.jpg` | Profile mark shown on every slide |
| `assets/fonts/` | Playfair Display + Inter (latin subsets) |
| `tojpeg.mjs` | PNG → JPEG for uploading or sharing |
| `video.mjs` | Slides → a self-swiping MP4 |
| `out/` | Rendered slides, `slide-01.png` … (plus `.jpg` copies) |
| `out/carousel.mp4` | The video cut of the deck |

## Video

```bash
npm i ffmpeg-static                          # once
node tools/church-carousel/video.mjs
```

Each slide holds for its own `hold` seconds (set per slide in `slides.json`),
then slides left as the next one arrives — a hands-free version of the swipe.
Output is H.264 1080×1350 with a silent audio track, since some platforms
mishandle a video with no audio at all.

Pace the `hold` values by how much there is to read: a full verse needs about
five seconds, a short line about three. Total runtime prints when the render
finishes.

`video.mjs` needs a full ffmpeg — H.264 and the `xfade` filter. The ffmpeg
bundled with Playwright's Chromium has neither (it only decodes MJPEG and
encodes VP8), so install `ffmpeg-static` or point `FFMPEG_PATH` at a real one.

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

Edit `slides.json` and re-render. Output is 1080×1350 (4:5) — the tallest
format Instagram and Facebook both accept, so it takes up the most feed space.

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
