// Line-art icon set for slide art. Stroke-based, inherits currentColor,
// drawn on a 100x100 grid so they scale cleanly to any slide size.
const P = (d, extra = "") => `<path d="${d}" ${extra}/>`;

export const ICONS = {
  shield:
    P("M50 8 12 24v26c0 22 16 34 38 42 22-8 38-20 38-42V24L50 8Z") +
    P("M33 50 45 62 68 39"),
  database:
    `<ellipse cx="50" cy="22" rx="34" ry="12"/>` +
    P("M16 22v56c0 6.6 15.2 12 34 12s34-5.4 34-12V22") +
    P("M16 50c0 6.6 15.2 12 34 12s34-5.4 34-12"),
  server:
    `<rect x="12" y="16" width="76" height="28" rx="6"/>` +
    `<rect x="12" y="56" width="76" height="28" rx="6"/>` +
    P("M26 30h.5M26 70h.5", 'stroke-linecap="round"') +
    P("M44 30h30M44 70h30"),
  clock: `<circle cx="50" cy="50" r="38"/>` + P("M50 26v26l18 11"),
  lock:
    `<rect x="18" y="44" width="64" height="44" rx="9"/>` +
    P("M32 44V32a18 18 0 0 1 36 0v12") +
    P("M50 62v10", 'stroke-linecap="round"'),
  key: `<circle cx="32" cy="50" r="18"/>` + P("M50 50h38M76 50v14M64 50v10"),
  retry:
    P("M84 50a34 34 0 1 1-10-24") +
    P("M76 12v16H60", 'stroke-linejoin="round"'),
  queue:
    `<rect x="8" y="34" width="24" height="32" rx="5"/>` +
    `<rect x="38" y="34" width="24" height="32" rx="5"/>` +
    `<rect x="68" y="34" width="24" height="32" rx="5"/>`,
  cpu:
    `<rect x="24" y="24" width="52" height="52" rx="8"/>` +
    `<rect x="40" y="40" width="20" height="20" rx="3"/>` +
    P("M40 8v16M60 8v16M40 76v16M60 76v16M8 40h16M8 60h16M76 40h16M76 60h16"),
  network:
    `<circle cx="50" cy="18" r="11"/><circle cx="18" cy="80" r="11"/><circle cx="82" cy="80" r="11"/>` +
    P("M50 29v22M50 51 24 70M50 51l26 19"),
  disk: `<circle cx="50" cy="50" r="38"/><circle cx="50" cy="50" r="10"/>` + P("M63 37 76 24"),
  alert:
    P("M50 12 8 84h84L50 12Z", 'stroke-linejoin="round"') +
    P("M50 40v20", 'stroke-linecap="round"') +
    P("M50 71h.5", 'stroke-linecap="round"'),
  bolt: P("M56 6 22 56h22l-6 38 34-50H50l6-38Z", 'stroke-linejoin="round"'),
  split: P("M12 50h20l14-24h42M46 74h42M32 50l14 24") + P("M76 14l14 12-14 12M76 62l14 12-14 12"),
  memory:
    `<rect x="16" y="28" width="68" height="44" rx="7"/>` +
    P("M30 44v12M44 44v12M58 44v12M72 44v12") +
    P("M30 28V14M50 28V14M70 28V14M30 86V72M50 86V72M70 86V72"),
  file:
    P("M26 8h32l20 20v64a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4V12a4 4 0 0 1 4-4Z") +
    P("M58 8v20h20"),
};

export function icon(name, { size = 300, color = "currentColor", width = 6 } = {}) {
  const body = ICONS[name];
  if (!body) throw new Error(`Unknown icon: ${name} (have: ${Object.keys(ICONS).join(", ")})`);
  return `<svg viewBox="0 0 100 100" width="${size}" height="${size}" fill="none"
    stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true">${body}</svg>`;
}
