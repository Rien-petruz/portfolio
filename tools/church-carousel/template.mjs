// Slide markup + styling for The NewWine Place carousel.
// `*word*` marks a highlighted phrase, `\n` a line break, `\n\n` a paragraph.
//
// A post picks its look with `theme` — the colours all come from the logo, so
// the decks stay a family while no two consecutive posts look the same.

export const THEMES = {
  // Near-black with the logo's purple and red glowing in from the corners.
  night: {
    ground: '#0b0b10',
    text: '#f4f2ee',
    textRgb: '244, 242, 238',
    accent: '#f5c518',
    accentRgb: '245, 197, 24',
    glow1: 'rgba(160, 43, 217, 0.30)',
    glow2: 'rgba(229, 27, 35, 0.26)',
    wash: 'rgba(245, 197, 24, 0.055)',
    grainOpacity: 0.5,
    grainBlend: 'overlay',
    shadow: 'rgba(0, 0, 0, 0.45)',
  },
  // Warm bone paper, plum ink, the logo's purple carrying the emphasis.
  parchment: {
    ground: '#efe8da',
    text: '#241026',
    textRgb: '36, 16, 38',
    accent: '#7a1ba5',
    accentRgb: '122, 27, 165',
    glow1: 'rgba(184, 134, 11, 0.30)',
    glow2: 'rgba(122, 27, 165, 0.18)',
    wash: 'rgba(196, 146, 32, 0.10)',
    grainOpacity: 0.28,
    grainBlend: 'multiply',
    shadow: 'rgba(36, 16, 38, 0.20)',
  },
};

const esc = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const inline = (s) =>
  esc(s).replace(/\*([^*]+)\*/g, '<em class="hl">$1</em>');

const lines = (s) =>
  inline(s)
    .split('\n\n')
    .map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`)
    .join('');

const css = (fonts, size, padBottom, t) => `
  @font-face { font-family: 'Inter'; src: url(${fonts.inter}) format('woff2'); font-weight: 100 900; }
  @font-face { font-family: 'Playfair'; src: url(${fonts.playfair}) format('woff2'); font-weight: 400 900; }
  @font-face { font-family: 'Playfair'; src: url(${fonts.playfairItalic}) format('woff2'); font-weight: 400 900; font-style: italic; }

  :root {
    --ink: ${t.ground};
    --paper: ${t.text};
    --gold: ${t.accent};
    --muted: rgba(${t.textRgb}, 0.64);
    --body: rgba(${t.textRgb}, 0.88);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body { width: ${size.width}px; height: ${size.height}px; overflow: hidden; background: var(--ink); }

  .slide {
    position: relative;
    width: ${size.width}px;
    height: ${size.height}px;
    padding: 72px 84px ${padBottom}px;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    overflow: hidden;
    background:
      radial-gradient(820px 620px at 88% -6%, ${t.glow1}, transparent 62%),
      radial-gradient(760px 640px at -12% 104%, ${t.glow2}, transparent 60%),
      radial-gradient(1000px 900px at 50% 42%, ${t.wash}, transparent 70%),
      var(--ink);
    color: var(--paper);
    font-family: 'Inter', sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  /* Paper-grain texture, echoing the wall in the logo lockup. */
  .slide::before {
    content: '';
    position: absolute;
    inset: 0;
    opacity: ${t.grainOpacity};
    mix-blend-mode: ${t.grainBlend};
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/></filter><rect width='220' height='220' filter='url(%23n)' opacity='0.42'/></svg>");
  }

  .slide::after {
    content: '';
    position: absolute;
    inset: 38px;
    border: 1px solid rgba(${t.accentRgb}, 0.22);
    border-radius: 10px;
    pointer-events: none;
  }

  .slide > * { position: relative; z-index: 1; }

  /* ---------- header ---------- */
  .head { display: flex; align-items: center; gap: 22px; }
  .avatar {
    width: 96px; height: 96px; border-radius: 50%;
    overflow: hidden; background: #fff; flex: none;
    border: 3px solid rgba(${t.accentRgb}, 0.85);
    box-shadow: 0 10px 34px ${t.shadow};
  }
  /* The supplied logo sits on a wide mock-up wall — zoom past the padding
     so the mark itself reads at avatar size. */
  .avatar img { width: 100%; height: 100%; object-fit: cover; transform: scale(1.42); }
  .handle { font-size: 31px; font-weight: 700; letter-spacing: -0.2px; }
  .church { font-size: 22px; font-weight: 500; color: var(--muted); margin-top: 5px; letter-spacing: 0.5px; }

  /* ---------- shared type ---------- */
  .body { min-height: 0; display: flex; flex-direction: column; justify-content: center; padding: 40px 0; }

  .eyebrow {
    display: inline-flex; align-items: center; gap: 14px; align-self: flex-start;
    font-size: 22px; font-weight: 700; letter-spacing: 3.4px; text-transform: uppercase;
    color: var(--gold);
  }
  .eyebrow::before { content: ''; width: 54px; height: 2px; background: var(--gold); opacity: 0.7; }

  h1 {
    font-family: 'Playfair', serif;
    font-weight: 800;
    font-size: 100px;
    line-height: 1.04;
    letter-spacing: -1.6px;
    margin-top: 38px;
  }

  .hl { font-style: italic; color: var(--gold); }

  .sub {
    margin-top: 38px;
    font-size: 33px;
    line-height: 1.52;
    color: var(--muted);
    max-width: 830px;
  }

  .lead {
    font-family: 'Playfair', serif;
    font-weight: 700;
    font-size: 76px;
    line-height: 1.14;
    letter-spacing: -1px;
  }

  .text { margin-top: 44px; font-size: 42px; line-height: 1.56; color: var(--body); }
  .text p + p { margin-top: 30px; }

  .kicker {
    font-family: 'Playfair', serif;
    font-size: 30px; font-weight: 700; color: var(--gold);
    opacity: 0.9; letter-spacing: 1px; margin-bottom: 30px;
  }

  /* ---------- verse ---------- */
  .verse {
    font-family: 'Playfair', serif;
    font-style: italic;
    font-weight: 500;
    font-size: 62px;
    line-height: 1.34;
    margin-top: 44px;
    padding-left: 40px;
    border-left: 4px solid rgba(${t.accentRgb}, 0.6);
  }
  .ref { margin-top: 40px; padding-left: 44px; font-size: 28px; font-weight: 700; letter-spacing: 2.6px; text-transform: uppercase; color: var(--gold); }

  /* ---------- quote ---------- */
  .mark { font-family: 'Playfair', serif; font-size: 190px; line-height: 0.6; color: var(--gold); opacity: 0.42; height: 108px; }
  .quote { font-family: 'Playfair', serif; font-weight: 700; font-size: 68px; line-height: 1.26; letter-spacing: -0.6px; }

  /* ---------- closing ---------- */
  .closing { text-align: center; align-items: center; }
  .closing h1 { font-size: 112px; margin-top: 0; }
  .rule { width: 92px; height: 3px; background: var(--gold); margin: 54px 0 46px; }
  .author { font-size: 46px; font-weight: 800; letter-spacing: -0.4px; }
  .byline { margin-top: 16px; font-size: 26px; font-weight: 600; letter-spacing: 3px; text-transform: uppercase; color: var(--muted); }
  .cta {
    margin-top: 62px; padding: 22px 44px; border-radius: 999px;
    border: 1px solid rgba(${t.accentRgb}, 0.5); background: rgba(${t.accentRgb}, 0.10);
    font-size: 27px; font-weight: 700; letter-spacing: 0.4px; color: var(--gold);
  }

  /* ---------- footer ---------- */
  .foot { display: flex; align-items: center; justify-content: space-between; font-size: 23px; font-weight: 600; letter-spacing: 2.4px; text-transform: uppercase; color: var(--muted); }
  .dots { display: flex; gap: 11px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: rgba(${t.textRgb}, 0.26); }
  .dot.on { background: var(--gold); transform: scale(1.32); }
  .cue { color: var(--gold); }
`;

function head(brand, avatar) {
  return `<header class="head">
      <span class="avatar"><img src="${avatar}" alt=""></span>
      <div>
        <div class="handle">${esc(brand.handle)}</div>
        <div class="church">${esc(brand.church)}</div>
      </div>
    </header>`;
}

function foot(index, total, cue, LAST_FOOT) {
  const dots = Array.from({ length: total }, (_, i) => `<span class="dot${i === index ? ' on' : ''}"></span>`).join('');
  const right = index === total - 1 ? esc(LAST_FOOT) : `<span class="cue">${esc(cue || 'Swipe →')}</span>`;
  return `<footer class="foot">
      <span>${String(index + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}</span>
      <span class="dots">${dots}</span>
      ${right}
    </footer>`;
}

function content(slide) {
  switch (slide.type) {
    case 'hook':
      return `<div class="body">
        <span class="eyebrow">${esc(slide.eyebrow)}</span>
        <h1>${inline(slide.title).replace(/\n/g, '<br>')}</h1>
        <div class="sub">${lines(slide.sub)}</div>
      </div>`;
    case 'verse':
      return `<div class="body">
        <span class="eyebrow">${esc(slide.eyebrow)}</span>
        <div class="verse">${inline(slide.verse)}</div>
        <div class="ref">${esc(slide.ref)}</div>
      </div>`;
    case 'quote':
      return `<div class="body">
        <div class="mark">&ldquo;</div>
        <div class="quote">${inline(slide.quote)}</div>
      </div>`;
    case 'closing':
      return `<div class="body closing">
        <h1>${inline(slide.title).replace(/\n/g, '<br>')}</h1>
        <div class="rule"></div>
        <div class="author">${esc(slide.author)}</div>
        <div class="byline">${esc(slide.church)}</div>
        <div class="cta">${esc(slide.cta)}</div>
      </div>`;
    default:
      return `<div class="body">
        ${slide.kicker ? `<div class="kicker">${esc(slide.kicker)}</div>` : ''}
        <div class="lead">${inline(slide.lead)}</div>
        <div class="text">${lines(slide.body)}</div>
      </div>`;
  }
}

export function renderSlide({ slide, index, total, brand, avatar, fonts, format, theme = 'night' }) {
  const size = { width: format.width, height: format.height };
  const t = THEMES[theme];
  if (!t) throw new Error(`Unknown theme "${theme}". Have: ${Object.keys(THEMES).join(', ')}`);
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>${css(fonts, size, format.padBottom ?? 66, t)}</style></head>
<body><section class="slide">
    ${head(brand, avatar)}
    ${content(slide)}
    ${foot(index, total, slide.cue, brand.handle)}
  </section></body></html>`;
}
