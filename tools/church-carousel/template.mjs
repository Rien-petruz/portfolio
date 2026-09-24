// Slide markup + styling for The NewWine Place carousel.
// `*word*` marks a highlighted phrase, `\n` a line break, `\n\n` a paragraph.
//
// A post picks its look with `theme` — the colours all come from the logo, so
// the decks stay a family while no two consecutive posts look the same.

// Original line-art motifs, drawn to carry the beat of a slide without
// competing with the type. Stroked in the theme accent at low opacity, set in
// the empty band under the header. A slide opts in with `art: "<name>"`.
export const MOTIFS = {
  // a span joining two sides
  bridge: `<path d="M6 88 h88"/><path d="M14 88 V54"/><path d="M86 88 V54"/><path d="M14 54 q36 -34 72 0"/><path d="M34 88 V62"/><path d="M50 88 V58"/><path d="M66 88 V62"/>`,

  // an open book
  book: `<path d="M50 32 v56"/><path d="M50 32 q-20 -10 -42 -5 v54 q22 -5 42 5"/><path d="M50 32 q20 -10 42 -5 v54 q-22 -5 -42 5"/>`,

  // a voice carrying
  voice: `<circle cx="18" cy="50" r="7"/><path d="M34 36 q13 14 0 28"/><path d="M50 26 q21 24 0 48"/><path d="M66 16 q29 34 0 68"/>`,

  // a scroll
  scroll: `<path d="M28 24 h44 v52 h-44 z"/><path d="M28 24 a6 6 0 0 1 0 -12 h44 a6 6 0 0 1 0 12"/>
    <path d="M28 76 a6 6 0 0 0 0 12 h44 a6 6 0 0 0 0 -12"/><path d="M40 40 h20"/><path d="M40 52 h20"/>`,

  // light coming up over the horizon
  dawn: `<path d="M12 74 h76"/><path d="M32 74 a18 18 0 0 1 36 0"/><path d="M50 38 v-12"/>
    <path d="M28 50 l-9 -9"/><path d="M72 50 l9 -9"/><path d="M18 64 l-11 -5"/><path d="M82 64 l11 -5"/>`,

  // fire
  flame: `<path d="M50 88 c-16 0 -26 -11 -26 -24 c0 -17 14 -23 16 -42 c10 8 15 17 15 25 c4 -4 6 -10 6 -16 c10 11 15 23 15 33 c0 13 -10 24 -26 24 z"/>`,

  // a balance holding two things at once
  scales: `<path d="M50 20 v54"/><path d="M50 74 v14"/><path d="M38 88 h24"/><path d="M16 30 h68"/>
    <path d="M16 30 v8"/><path d="M84 30 v8"/><path d="M4 38 a12 10 0 0 0 24 0 z"/><path d="M72 38 a12 10 0 0 0 24 0 z"/><circle cx="50" cy="20" r="4"/>`,

  // a road running to the horizon
  road: `<path d="M8 96 L41 10"/><path d="M92 96 L59 10"/>
    <path d="M50 88 v-11"/><path d="M50 66 v-9"/><path d="M50 47 v-7"/><path d="M50 32 v-5"/>`,

  // a group standing at a distance
  figures: `<circle cx="22" cy="34" r="7"/><path d="M22 43 v20"/><path d="M11 52 h22"/><path d="M22 63 l-8 16"/><path d="M22 63 l8 16"/>
    <circle cx="50" cy="30" r="6"/><path d="M50 38 v18"/><path d="M40 46 h20"/><path d="M50 56 l-7 14"/><path d="M50 56 l7 14"/>
    <circle cx="76" cy="36" r="5"/><path d="M76 43 v15"/><path d="M68 50 h16"/><path d="M76 58 l-6 12"/><path d="M76 58 l6 12"/>`,

  // a doorway to walk through
  door: `<path d="M26 92 V34 a24 24 0 0 1 48 0 v58"/><path d="M14 92 h72"/><path d="M50 10 v82"/><circle cx="40" cy="60" r="3"/>`,

  // footprints going on ahead
  steps: `<ellipse cx="34" cy="86" rx="7" ry="10"/><ellipse cx="62" cy="70" rx="6.5" ry="9.5"/>
    <ellipse cx="38" cy="53" rx="6" ry="9"/><ellipse cx="64" cy="37" rx="5.5" ry="8"/><ellipse cx="42" cy="22" rx="5" ry="7.5"/>`,

  // a vessel pouring out
  jar: `<path d="M34 24 h32 l-4 14 a22 22 0 0 1 -24 0 z"/><path d="M38 38 a22 26 0 0 0 24 0 l3 38 a16 8 0 0 1 -30 0 z"/>
    <path d="M66 30 q14 6 14 22"/><path d="M80 56 v14"/><path d="M74 74 h12 l-2 16 h-8 z"/>`,

  // waters standing apart, dry ground between
  river: `<path d="M20 14 q-8 12 0 24 q8 12 0 24 q-8 12 0 24"/><path d="M80 14 q8 12 0 24 q-8 12 0 24 q8 12 0 24"/>
    <path d="M38 92 V24"/><path d="M62 92 V24"/><path d="M46 80 h8"/><path d="M46 62 h8"/><path d="M46 44 h8"/>`,

  // forward
  arrow: `<path d="M18 26 L44 52 L18 78"/><path d="M44 26 L70 52 L44 78"/><path d="M70 26 L96 52 L70 78"/>`,

  // something waiting further along the path
  marker: `<path d="M18 94 q26 -16 22 -36 q-4 -20 20 -28 q16 -5 24 6"/>
    <path d="M78 14 l5 11 12 2 -9 9 2 12 -10 -6 -11 6 2 -12 -8 -9 12 -2 z"/>`,
};

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
  // Near-black with a pine cast, warmed by gold and red at the corners, and
  // the only dark palette that emphasises in the logo's purple rather than gold.
  vigil: {
    ground: '#101614',
    text: '#eef2ef',
    textRgb: '238, 242, 239',
    accent: '#b57bff',
    accentRgb: '181, 123, 255',
    glow1: 'rgba(245, 197, 24, 0.20)',
    glow2: 'rgba(229, 27, 35, 0.26)',
    wash: 'rgba(181, 123, 255, 0.05)',
    grainOpacity: 0.45,
    grainBlend: 'overlay',
    shadow: 'rgba(0, 0, 0, 0.50)',
  },
  // Deep violet after dark, lit by the logo's purple and red — and the only
  // palette that carries its emphasis in coral rather than gold.
  nocturne: {
    ground: '#17112e',
    text: '#f0ecf7',
    textRgb: '240, 236, 247',
    accent: '#ff7a59',
    accentRgb: '255, 122, 89',
    glow1: 'rgba(160, 43, 217, 0.34)',
    glow2: 'rgba(229, 27, 35, 0.24)',
    wash: 'rgba(255, 122, 89, 0.05)',
    grainOpacity: 0.45,
    grainBlend: 'overlay',
    shadow: 'rgba(0, 0, 0, 0.50)',
  },
  // Deep sea-blue before a storm, with the logo's purple and a cold steel
  // light at the corners, and gold holding the emphasis.
  tempest: {
    ground: '#0c1c2e',
    text: '#eaf1f7',
    textRgb: '234, 241, 247',
    accent: '#f5c518',
    accentRgb: '245, 197, 24',
    glow1: 'rgba(122, 27, 165, 0.32)',
    glow2: 'rgba(24, 104, 138, 0.42)',
    wash: 'rgba(245, 197, 24, 0.05)',
    grainOpacity: 0.45,
    grainBlend: 'overlay',
    shadow: 'rgba(0, 0, 0, 0.50)',
  },
  // Deep wine — the church's own name — with crimson and the logo's purple
  // burning in at the corners, and warm gold carrying the emphasis.
  vintage: {
    ground: '#2e0a12',
    text: '#f7efe4',
    textRgb: '247, 239, 228',
    accent: '#f0b429',
    accentRgb: '240, 180, 41',
    glow1: 'rgba(196, 30, 58, 0.34)',
    glow2: 'rgba(122, 27, 165, 0.26)',
    wash: 'rgba(240, 180, 41, 0.07)',
    grainOpacity: 0.42,
    grainBlend: 'overlay',
    shadow: 'rgba(0, 0, 0, 0.50)',
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

  /* ---------- motif ---------- */
  .motif {
    position: absolute;
    top: ${Math.round(padBottom > 120 ? 210 : 190)}px;
    right: 84px;
    width: 236px; height: 236px;
    color: var(--gold);
    opacity: 0.22;
    pointer-events: none;
  }
  .motif svg { width: 100%; height: 100%; display: block; }
  .motif path, .motif circle, .motif ellipse {
    fill: none; stroke: currentColor; stroke-width: 2.6;
    stroke-linecap: round; stroke-linejoin: round;
  }

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

function art(name) {
  const d = MOTIFS[name];
  if (!d) throw new Error(`Unknown motif "${name}". Have: ${Object.keys(MOTIFS).join(', ')}`);
  return `<div class="motif"><svg viewBox="0 0 100 100" aria-hidden="true">${d}</svg></div>`;
}

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

export function renderSlide({ slide, index, total, brand, avatar, fonts, format, theme = 'night', footer = true }) {
  const size = { width: format.width, height: format.height };
  const t = THEMES[theme];
  if (!t) throw new Error(`Unknown theme "${theme}". Have: ${Object.keys(THEMES).join(', ')}`);
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>${css(fonts, size, format.padBottom ?? 66, t)}</style></head>
<body><section class="slide">
    ${slide.art ? art(slide.art) : ''}
    ${head(brand, avatar)}
    ${content(slide)}
    ${footer ? foot(index, total, slide.cue, brand.handle) : ''}
  </section></body></html>`;
}
