// Rebuilds content/topics.json + content/master-list.md from the extracted docx text.
// Source of truth: tools/source/topics_raw.txt (verbatim extraction of the master list docx).
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const raw = readFileSync(join(root, "tools/source/topics_raw.txt"), "utf8").split("\n");

const sections = [];
let intro = [];
let current = null;
let tail = [];
let inTail = false;

const slug = (s) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);

for (const line of raw) {
  const h = line.match(/^\[Heading1\] (.+)$/);
  const li = line.match(/^\[List(?:Number|Bullet)\] (.+)$/);
  if (h) {
    const title = h[1].trim();
    const numbered = title.match(/^(\d+)\.\s*(.+)$/);
    if (!numbered) { inTail = true; tail.push({ heading: title, lines: [] }); current = null; continue; }
    inTail = false;
    current = { n: Number(numbered[1]), title: numbered[2].trim(), id: slug(numbered[2]), topics: [] };
    sections.push(current);
  } else if (li) {
    if (inTail) tail[tail.length - 1].lines.push(li[1].trim());
    else if (current) current.topics.push(li[1].trim());
  } else if (line.trim()) {
    if (inTail && tail.length) tail[tail.length - 1].lines.push(line.trim());
    else if (!current) intro.push(line.trim());
  }
}

// Preserve posting state across rebuilds — this script re-derives titles from the
// docx, but status/postedAt/postDir are earned data and must survive.
const prevPath = join(root, "content/topics.json");
const prev = existsSync(prevPath)
  ? new Map(JSON.parse(readFileSync(prevPath, "utf8")).topics.map((t) => [t.title, t]))
  : new Map();

let seq = 0;
const topics = [];
for (const s of sections) {
  s.topics.forEach((t, i) => {
    seq += 1;
    const old = prev.get(t);
    topics.push({
      id: `T${String(seq).padStart(3, "0")}`,
      section: s.n,
      sectionTitle: s.title,
      index: i + 1,
      title: t,
      status: old?.status ?? "queued",
      postedAt: old?.postedAt ?? null,
      postDir: old?.postDir ?? null,
    });
  });
}

const doc = {
  title: intro[0] || "Backend Engineering & System Architecture — Content Master List",
  positioning: intro.slice(1),
  sections: sections.map((s) => ({ n: s.n, id: s.id, title: s.title, count: s.topics.length })),
  formula: (tail.find((t) => /Formula/i.test(t.heading))?.lines) || [],
  direction: (tail.find((t) => /Direction/i.test(t.heading))?.lines) || [],
  totalTopics: topics.length,
  topics,
};

writeFileSync(join(root, "content/topics.json"), JSON.stringify(doc, null, 2) + "\n");

// Human-readable mirror
const md = [];
md.push(`# ${doc.title}`, "");
for (const p of doc.positioning) md.push(p, "");
md.push(`**${doc.totalTopics} topics across ${doc.sections.length} sections.**`, "");
md.push("## Post formula", "");
for (const f of doc.formula) md.push(`- ${f}`);
md.push("", "## Sections", "");
for (const s of doc.sections) md.push(`- **${s.n}. ${s.title}** — ${s.count} topics`);
md.push("");
for (const s of sections) {
  md.push(`## ${s.n}. ${s.title}`, "");
  for (const t of topics.filter((x) => x.section === s.n)) md.push(`- \`${t.id}\` ${t.title}`);
  md.push("");
}
for (const d of doc.direction) md.push(d, "");
writeFileSync(join(root, "content/master-list.md"), md.join("\n"));

console.log(`sections=${doc.sections.length} topics=${doc.totalTopics}`);
for (const s of doc.sections) console.log(`  ${String(s.n).padStart(2)}. ${s.title} — ${s.count}`);
