// Slide templates for the Backend Engineering series.
//
// Four themes, lifted from the reference art:
//   signature — Peter's own cover style: white/lavender, navy accent, big line icon
//   marker    — white, black headline, yellow highlighter, gold index
//   console   — browser-window card, blue kicker, comparison diagrams
//   blueprint — cream paper, serif numeral, hand-written subtitle, boxed architecture
//
// Every slide carries the author footer (headshot + name + handle). That is a
// brand rule, not a per-slide option.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { icon } from "./icons.mjs";
import { highlight, TOKEN_CSS } from "./highlight.mjs";

const esc = (s = "") =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Inline markup allowed in copy: *accent*, **bold**, ==highlight==, `code`
function rich(s = "") {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/==(.+?)==/g, '<span class="hl">$1</span>')
    .replace(/\*(.+?)\*/g, '<span class="accent">$1</span>')
    .replace(/`(.+?)`/g, '<code class="inline">$1</code>');
}

const dataUri = (root, rel, mime) =>
  `data:${mime};base64,${readFileSync(join(root, rel)).toString("base64")}`;

/* ---------------------------------------------------------------- assets -- */

export function assets(root, brand) {
  const f = (n) => dataUri(root, `brand/assets/fonts/${n}.woff2`, "font/woff2");
  return {
    avatar: dataUri(root, brand.author.avatar, "image/png"),
    fonts: {
      Inter: f("Inter"),
      JetBrainsMono: f("JetBrainsMono"),
      Caveat: f("Caveat"),
      SourceSerif4: f("SourceSerif4"),
    },
  };
}

/* -------------------------------------------------------------------- css -- */

export function css(brand, a, fmt) {
  const c = brand.color;
  const face = (family, url, weights = "100 900") =>
    `@font-face{font-family:"${family}";src:url(${url}) format("woff2");font-weight:${weights};font-style:normal;font-display:block}`;

  return `
${face(brand.font.display, a.fonts.Inter)}
${face(brand.font.mono, a.fonts.JetBrainsMono)}
${face(brand.font.serif, a.fonts.SourceSerif4)}
${face(brand.font.hand, a.fonts.Caveat, "400 700")}

*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  width:${fmt.w}px;
  font-family:"${brand.font.display}",system-ui,sans-serif;
  color:${c.ink};-webkit-font-smoothing:antialiased;
  text-rendering:geometricPrecision;
}
@page{size:${fmt.w}px ${fmt.h}px;margin:0}
.slide{break-after:page;page-break-after:always}
.slide:last-child{break-after:auto;page-break-after:auto}
.slide{
  position:relative;width:${fmt.w}px;height:${fmt.h}px;overflow:hidden;
  display:flex;flex-direction:column;padding:${fmt.pad || "84px"};
}
.slide>*{position:relative;z-index:2}
.bg{position:absolute;inset:0;z-index:0}

/* ---- shared type ---- */
.eyebrow{display:flex;align-items:center;gap:24px;font-size:31px;font-weight:800;letter-spacing:-.2px}
.eyebrow .bar{width:9px;height:46px;border-radius:5px;background:${c.navy};flex:none}
.headline{font-weight:800;letter-spacing:-3.4px;line-height:.99;margin:0;white-space:pre-line}
.headline .accent{color:${c.navy}}
.sub{font-size:35px;font-weight:500;line-height:1.42;color:${c.inkSoft};margin:0;white-space:pre-line}
.sub b{font-weight:800;color:${c.ink}}
.hl{background:${c.marker};padding:0 .12em;border-radius:4px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
code.inline{font-family:"${brand.font.mono}",monospace;font-size:.86em;background:${c.lavenderSoft};
  border:2px solid ${c.rule};border-radius:8px;padding:.06em .3em}
.spacer{flex:1 1 auto;min-height:0}

/* ---- author footer (on every slide) ---- */
.foot{display:flex;align-items:center;gap:28px;flex:none}
.foot .who{display:flex;align-items:center;gap:28px}
.foot img{width:112px;height:112px;border-radius:50%;object-fit:cover;flex:none;
  box-shadow:0 6px 22px rgba(5,6,15,.16)}
.foot .name{font-size:37px;font-weight:800;letter-spacing:-1px;line-height:1.12}
.foot .handle{font-size:29px;font-weight:500;color:${c.muted};line-height:1.2}
.foot .tail{margin-left:auto;display:flex;align-items:center;gap:18px;
  font-size:27px;font-weight:800;letter-spacing:1.5px;color:${c.muted}}
.foot--slim img{width:88px;height:88px}
.foot--slim .name{font-size:31px}
.foot--slim .handle{font-size:25px}

/* ---- counters ---- */
.counter{margin-left:auto;font-size:29px;font-weight:800}
.pill{margin-left:auto;background:${c.ink};color:#fff;border-radius:999px;
  padding:12px 30px;font-size:29px;font-weight:800;letter-spacing:.4px}

/* ---- theme: signature ---- */
.t-signature .bg{background:
  radial-gradient(105% 80% at 100% 0%, #cfd2ee 0%, rgba(207,210,238,.55) 32%, rgba(224,224,240,0) 66%),
  radial-gradient(85% 65% at 0% 100%, #e9ebfa 0%, rgba(233,235,250,0) 62%),
  ${c.paper};}
.t-signature .headline{font-size:118px}
.t-signature .art{position:absolute;right:${fmt.artRight || 78}px;bottom:${fmt.artBottom || Math.round(fmt.h * 0.23)}px;color:${c.navy};z-index:1}
.t-signature .swoosh{display:block;margin-top:-6px}
.t-signature .hl{background:${c.lavender};color:${c.navy};border-radius:7px;padding:0 .14em}

/* ---- theme: marker ---- */
.t-marker .bg{background:${c.paper}}
.t-marker .top{display:flex;align-items:baseline;font-size:31px;font-weight:600;color:${c.inkSoft}}
.t-marker .top .idx{color:${c.gold};font-weight:800}
.t-marker .headline{font-size:126px;letter-spacing:-4px}
.t-marker .sub{font-size:41px;color:${c.ink};font-weight:500}
.t-marker .doodle{position:absolute;right:96px;top:50%;color:${c.ink}}

/* ---- theme: console ---- */
.t-console .bg{background:${c.cream}}
.t-console .win{background:#fff;border:3px solid ${c.rule};border-radius:26px;
  box-shadow:0 26px 60px rgba(5,6,15,.09);overflow:hidden;display:flex;flex-direction:column;flex:1 1 auto;min-height:0}
.t-console .chrome{display:flex;align-items:center;gap:14px;padding:26px 34px;border-bottom:3px solid ${c.rule}}
.t-console .dot{width:22px;height:22px;border-radius:50%}
.t-console .win-body{padding:42px 46px;flex:1 1 auto;min-height:0;overflow:hidden;
  display:flex;flex-direction:column;justify-content:center}
.t-console .win-fit{display:flex;flex-direction:column;gap:24px;transform-origin:0 0;width:100%}
.t-console .kicker{font-size:44px;font-weight:800;letter-spacing:-1px;color:${c.muted}}
.t-console .kicker .n{color:${c.blue}}
.t-console .headline{font-size:86px;letter-spacing:-2.4px}
.t-console .mono{font-family:"${brand.font.mono}",monospace;font-size:36px;font-weight:500;color:${c.blue}}
.t-console .desc{font-size:33px;line-height:1.42;color:${c.inkSoft};white-space:pre-line}
.t-console .rule{height:5px;background:${c.rule};border-radius:3px;position:relative}
.t-console .rule::after{content:"";position:absolute;left:0;top:0;height:5px;width:26%;
  background:${c.blue};border-radius:3px}

/* ---- theme: blueprint ---- */
.t-blueprint .bg{background:${c.cream}}
.t-blueprint .headline{font-family:"${brand.font.serif}",Georgia,serif;font-size:82px;
  font-weight:700;color:${c.red};letter-spacing:-1.5px;line-height:1.06}
.t-blueprint .hand{font-family:"${brand.font.hand}",cursive;font-size:52px;font-weight:700;
  color:${c.ink};margin-top:6px}
.t-blueprint .hand-rule{display:block;margin-top:-2px}
.t-blueprint .callout{display:flex;align-items:center;gap:26px;border:4px dashed ${c.rule};
  border-radius:22px;padding:30px 34px;font-size:31px;line-height:1.38;color:${c.inkSoft};
  font-style:italic;font-family:"${brand.font.serif}",Georgia,serif}
.t-blueprint .callout .badge{width:66px;height:66px;border-radius:50%;background:${c.green};
  color:#fff;display:flex;align-items:center;justify-content:center;flex:none}

/* ---- blocks: flow diagram ---- */
.flow{display:flex;align-items:stretch;gap:0;flex:1 1 auto;min-height:0}
.flow .col{display:flex;flex-direction:column;justify-content:center;gap:24px;flex:1 1 0}
.flow .arrow{flex:0 0 132px;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:12px;color:${c.muted}}
.flow .arrow .lbl{font-size:23px;font-weight:700;text-align:center;line-height:1.2}
.node{border:4px solid ${c.ink};border-radius:18px;padding:22px 20px;text-align:center;background:#fff}
.node .l{font-size:32px;font-weight:800;letter-spacing:-.6px;line-height:1.14}
.node .s{font-size:25px;font-weight:500;color:${c.muted};margin-top:5px}
.node--amber{background:#fdf1d8;border-color:#c99a2e}
.node--violet{background:#efe9fb;border-color:#7c4dd6}
.node--green{background:${c.greenSoft};border-color:${c.green}}
.node--red{background:${c.redSoft};border-color:${c.red}}
.node--blue{background:#e8effd;border-color:${c.blue}}
.node--plain{background:#fff;border-color:${c.rule}}

/* ---- blocks: compare ---- */
.cmp{display:flex;flex-direction:column;gap:22px}
.cmp .lane{display:flex;align-items:center;gap:22px}
.cmp .tag{font-family:"${brand.font.mono}",monospace;font-size:24px;font-weight:700;
  letter-spacing:2px;text-transform:uppercase}
.cmp .bad .tag{color:${c.red}} .cmp .good .tag{color:${c.green}}
.cmp .box{border:4px solid;border-radius:14px;padding:16px 20px;font-family:"${brand.font.mono}",monospace;
  font-size:25px;font-weight:500;background:#fff;overflow-wrap:anywhere}
.cmp .bad .box{border-color:${c.red}} .cmp .good .box{border-color:${c.green}}
.cmp .verdict{display:flex;align-items:center;gap:14px;font-size:28px;font-weight:700;line-height:1.28}
.cmp .bad .verdict{color:${c.red}} .cmp .good .verdict{color:${c.green}}
.cmp .sep{height:4px;background:${c.rule};border-radius:2px}
.cmp .arw{color:${c.muted};flex:none}

/* ---- blocks: code ---- */
.codewin{border:4px solid ${c.ink};border-radius:22px;overflow:hidden;background:#fff;
  display:flex;flex-direction:column;flex:1 1 auto;min-height:0}
.codewin .bar{display:flex;align-items:center;gap:14px;padding:17px 24px;background:${c.ink};color:#fff}
.codewin .bar .t{font-family:"${brand.font.mono}",monospace;font-size:26px;font-weight:500;opacity:.92}
.codewin .bar .lang{margin-left:auto;font-size:22px;font-weight:700;letter-spacing:2px;
  text-transform:uppercase;opacity:.65}
.codewin pre{margin:0;padding:28px 30px;overflow:hidden;flex:1 1 auto;min-height:0;
  display:flex;flex-direction:column;justify-content:center}
.codewin code{font-family:"${brand.font.mono}",monospace;font-size:29px;line-height:1.46;
  white-space:pre;display:block;color:${c.ink}}
.codenote{font-size:27px;line-height:1.38;color:${c.inkSoft};display:flex;gap:14px;align-items:flex-start}
.codenote .m{color:${c.blue};font-weight:800;flex:none}

/* ---- blocks: list ---- */
.list{display:flex;flex-direction:column;gap:24px}
.list li{display:flex;gap:20px;align-items:flex-start;font-size:32px;line-height:1.32;font-weight:500}
.list ul,.list ol{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:20px}
.list .n{font-family:"${brand.font.mono}",monospace;font-weight:700;color:${c.navy};flex:none;
  font-size:31px;padding-top:5px}

/* ---- takeaway ---- */
.t-takeaway .bg{background:${c.ink}}
.t-takeaway{color:#fff}
.t-takeaway .headline{font-size:88px;color:#fff;letter-spacing:-2.4px;line-height:1.1}
.t-takeaway .headline .accent{color:#8ea2ff}
.t-takeaway .sub{color:#aeb6ce}
.t-takeaway .eyebrow .bar{background:#8ea2ff}
.t-takeaway .foot .handle{color:#8b93ad}
.t-takeaway .foot .tail{color:#8b93ad}
.t-takeaway .cta{border-top:4px solid rgba(255,255,255,.16);padding-top:34px;
  font-size:33px;font-weight:600;color:#cfd5e8}

${TOKEN_CSS({ mono: brand.font.mono })}
`;
}

/* ------------------------------------------------------------ fragments -- */

const footer = (brand, a, { tail = "", slim = false } = {}) => `
<footer class="foot${slim ? " foot--slim" : ""}">
  <div class="who">
    <img src="${a.avatar}" alt="${esc(brand.author.name)}">
    <div>
      <div class="name">${esc(brand.author.name)}</div>
      <div class="handle">${esc(brand.author.handle)}</div>
    </div>
  </div>
  ${tail ? `<div class="tail">${tail}</div>` : ""}
</footer>`;

const swoosh = (color, w = 460) => `
<svg class="swoosh" width="${w}" height="34" viewBox="0 0 ${w} 34" fill="none">
  <path d="M6 24C${w * 0.28} 6 ${w * 0.66} 4 ${w - 6} 16" stroke="${color}"
    stroke-width="11" stroke-linecap="round"/>
</svg>`;

const handRule = (color, w = 300) => `
<svg class="hand-rule" width="${w}" height="20" viewBox="0 0 ${w} 20" fill="none">
  <path d="M4 14C${w * 0.3} 4 ${w * 0.62} 4 ${w - 4} 12" stroke="${color}"
    stroke-width="7" stroke-linecap="round"/>
</svg>`;

const arrowRight = (color, w = 92) => `
<svg width="${w}" height="26" viewBox="0 0 ${w} 26" fill="none">
  <path d="M2 13h${w - 20}" stroke="${color}" stroke-width="5" stroke-linecap="round"
    stroke-dasharray="11 9"/>
  <path d="M${w - 24} 4l14 9-14 9" stroke="${color}" stroke-width="5"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

const doodleArrow = (color) => `
<svg class="doodle" width="230" height="270" viewBox="0 0 230 270" fill="none">
  <path d="M20 16C96 44 152 96 150 160c-1 42-44 62-72 44-24-16-8-52 22-50 46 3 74 46 66 96"
    stroke="${color}" stroke-width="7" stroke-linecap="round" stroke-dasharray="16 14"/>
  <path d="M8 6l20 8-6 22" stroke="${color}" stroke-width="7"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

const chrome = (c) => `
<div class="chrome">
  <span class="dot" style="background:#f0b429"></span>
  <span class="dot" style="background:#2563eb"></span>
  <span class="dot" style="background:#1a7f4b"></span>
</div>`;

/* ---------------------------------------------------------------- blocks -- */

function block(b, brand) {
  if (!b) return "";
  const c = brand.color;
  switch (b.kind) {
    case "flow": {
      const cols = b.columns.map(
        (col) => `<div class="col">${col.nodes
          .map((n) => `<div class="node node--${n.tone || "plain"}">
              <div class="l">${rich(n.label)}</div>
              ${n.sub ? `<div class="s">${rich(n.sub)}</div>` : ""}
            </div>`).join("")}</div>`
      );
      const gaps = (b.connectors || []).map(
        (lbl) => `<div class="arrow">${lbl ? `<div class="lbl">${rich(lbl)}</div>` : ""}
          ${arrowRight(c.muted, 104)}</div>`
      );
      const out = [];
      cols.forEach((col, i) => { out.push(col); if (gaps[i]) out.push(gaps[i]); });
      return `<div class="flow">${out.join("")}</div>`;
    }
    case "compare": {
      const lane = (l, tone) => `
        <div class="lane ${tone}">
          <div style="flex:1.3 1 0;min-width:0">
            <div class="tag">${esc(l.tag)}</div>
            <div class="box" style="margin-top:12px">${rich(l.code)}</div>
          </div>
          <div class="arw">${arrowRight(c.muted, 82)}</div>
          <div class="verdict" style="flex:1 1 0;min-width:0">${rich(l.verdict)}</div>
        </div>`;
      return `<div class="cmp">
        ${lane(b.bad, "bad")}
        <div class="sep"></div>
        ${lane(b.good, "good")}
      </div>`;
    }
    case "code":
      return codeWindow(b, brand);
    case "list": {
      const items = b.items.map(
        (it, i) => `<li><span class="n">${b.ordered === false ? "—" : String(i + 1).padStart(2, "0")}</span>
          <span>${rich(it)}</span></li>`
      ).join("");
      return `<div class="list"><ul>${items}</ul></div>`;
    }
    default:
      throw new Error(`Unknown block kind: ${b.kind}`);
  }
}

function codeWindow(b, brand) {
  const body = highlight(b.code.replace(/\n+$/, ""), b.lang || "js");
  return `
<div class="codewin">
  <div class="bar">
    <span class="dot" style="width:18px;height:18px;border-radius:50%;background:#ff5f57"></span>
    <span class="dot" style="width:18px;height:18px;border-radius:50%;background:#febc2e"></span>
    <span class="dot" style="width:18px;height:18px;border-radius:50%;background:#28c840"></span>
    <span class="t" style="margin-left:14px">${esc(b.file || "")}</span>
    <span class="lang">${esc(b.lang || "js")}</span>
  </div>
  <pre><code class="code">${body}</code></pre>
</div>`;
}

/* ----------------------------------------------------------------- types -- */

const TYPES = {
  cover(s, { brand, a }) {
    const c = brand.color;
    const art = s.icon
      ? `<div class="art">${icon(s.icon, { size: s.iconSize || 330, color: c.navy, width: 5.4 })}</div>`
      : "";
    return `
<div class="slide t-signature">
  <div class="bg"></div>${art}
  <div class="eyebrow"><span class="bar"></span><span>${esc(s.eyebrow || brand.series)}</span></div>
  <div class="spacer"></div>
  <h1 class="headline" style="${s.headlineSize ? `font-size:${s.headlineSize}px` : ""}">${rich(s.headline)}</h1>
  ${s.underline === false ? "" : swoosh(c.navy, s.underlineWidth || 430)}
  ${s.sub ? `<p class="sub" style="margin-top:44px;max-width:${s.subWidth || 660}px">${rich(s.sub)}</p>` : ""}
  <div class="spacer"></div>
  ${footer(brand, a)}
</div>`;
  },

  statement(s, { brand, a, ctx }) {
    const c = brand.color;
    return `
<div class="slide t-marker">
  <div class="bg"></div>
  ${s.doodle ? doodleArrow(c.ink) : ""}
  <div class="top">
    <span>${esc(s.kicker || ctx.series)}</span>
    <span class="counter idx">#${s.index ?? ctx.n}</span>
  </div>
  <div class="spacer"></div>
  <h1 class="headline" style="${s.headlineSize ? `font-size:${s.headlineSize}px` : ""}">${rich(s.headline)}</h1>
  ${s.sub ? `<p class="sub" style="margin-top:52px;max-width:${s.subWidth || 830}px">${rich(s.sub)}</p>` : ""}
  <div class="spacer"></div>
  ${s.block ? `<div style="margin-bottom:44px">${block(s.block, brand)}</div>` : ""}
  ${footer(brand, a, { tail: ctx.last ? "" : "SWIPE" })}
</div>`;
  },

  concept(s, { brand, a, ctx }) {
    return `
<div class="slide t-console">
  <div class="bg"></div>
  <div class="win">
    ${chrome(brand.color)}
    <div class="win-body"><div class="win-fit">
      <div style="display:flex;align-items:baseline">
        <span class="kicker"><span class="n">${esc(s.number || String(ctx.n).padStart(2, "0"))}.</span>
          ${esc((s.label || brand.series).toUpperCase())}</span>
        <span class="counter" style="color:${brand.color.muted}">${ctx.n}/${ctx.total}</span>
      </div>
      <h1 class="headline">${rich(s.headline)}</h1>
      ${s.mono ? `<div class="mono">${rich(s.mono)}</div>` : ""}
      ${s.desc ? `<div class="desc">${rich(s.desc)}</div>` : ""}
      <div class="rule"></div>
      ${s.block ? block(s.block, brand) : ""}
    </div></div>
  </div>
  <div style="height:40px"></div>
  ${footer(brand, a, { slim: true, tail: ctx.last ? "" : "SWIPE" })}
</div>`;
  },

  code(s, { brand, a, ctx }) {
    return `
<div class="slide t-console">
  <div class="bg"></div>
  <div class="eyebrow"><span class="bar"></span><span>${esc(s.eyebrow || brand.series)}</span>
    <span class="pill">${ctx.n}/${ctx.total}</span></div>
  <h1 class="headline" style="font-size:${s.headlineSize || 54}px;letter-spacing:-1.8px;margin:30px 0 24px">${rich(s.headline)}</h1>
  ${codeWindow(s, brand)}
  ${s.note ? `<div class="codenote" style="margin-top:24px"><span class="m">→</span><span>${rich(s.note)}</span></div>` : ""}
  <div style="height:30px"></div>
  ${footer(brand, a, { slim: true, tail: ctx.last ? "" : "SWIPE" })}
</div>`;
  },

  flow(s, { brand, a, ctx }) {
    const c = brand.color;
    return `
<div class="slide t-blueprint">
  <div class="bg"></div>
  <div style="display:flex;align-items:flex-start">
    <div>
      <h1 class="headline">${rich(s.headline)}</h1>
      ${s.hand ? `<div class="hand">${rich(s.hand)}</div>${handRule(c.green, s.handRule || 290)}` : ""}
    </div>
    <span class="pill">${ctx.n}/${ctx.total}</span>
  </div>
  <div style="height:52px"></div>
  ${block({ kind: "flow", ...s.diagram }, brand)}
  <div style="height:46px"></div>
  ${s.callout
    ? `<div class="callout"><span class="badge">${icon("bolt", { size: 34, color: "#fff", width: 7 })}</span>
        <span>${rich(s.callout)}</span></div>`
    : ""}
  <div style="height:40px"></div>
  ${footer(brand, a, { slim: true, tail: ctx.last ? "" : "SWIPE" })}
</div>`;
  },

  compare(s, { brand, a, ctx }) {
    return `
<div class="slide t-console">
  <div class="bg"></div>
  <div class="win">
    ${chrome(brand.color)}
    <div class="win-body"><div class="win-fit">
      <div style="display:flex;align-items:baseline">
        <span class="kicker"><span class="n">${esc(s.number || String(ctx.n).padStart(2, "0"))}.</span>
          ${esc((s.label || "THE FIX").toUpperCase())}</span>
        <span class="counter" style="color:${brand.color.muted}">${ctx.n}/${ctx.total}</span>
      </div>
      <h1 class="headline">${rich(s.headline)}</h1>
      ${s.desc ? `<div class="desc">${rich(s.desc)}</div>` : ""}
      <div class="rule"></div>
      ${block({ kind: "compare", bad: s.bad, good: s.good }, brand)}
    </div></div>
  </div>
  <div style="height:40px"></div>
  ${footer(brand, a, { slim: true, tail: ctx.last ? "" : "SWIPE" })}
</div>`;
  },

  takeaway(s, { brand, a }) {
    return `
<div class="slide t-takeaway">
  <div class="bg"></div>
  <div class="eyebrow"><span class="bar"></span><span>${esc(s.eyebrow || "TAKEAWAY")}</span></div>
  <div class="spacer"></div>
  <h1 class="headline" style="${s.headlineSize ? `font-size:${s.headlineSize}px` : ""}">${rich(s.headline)}</h1>
  ${s.sub ? `<p class="sub" style="margin-top:40px;max-width:${s.subWidth || 800}px">${rich(s.sub)}</p>` : ""}
  <div class="spacer"></div>
  ${s.cta ? `<div class="cta" style="margin-bottom:40px">${rich(s.cta)}</div>` : ""}
  ${footer(brand, a)}
</div>`;
  },
};

export function slideHTML(slide, ctx) {
  const fn = TYPES[slide.type];
  if (!fn) throw new Error(`Unknown slide type: ${slide.type} (have: ${Object.keys(TYPES).join(", ")})`);
  return fn(slide, ctx);
}

export const SLIDE_TYPES = Object.keys(TYPES);
