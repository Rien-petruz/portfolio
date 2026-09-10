// Daily driver for the content queue.
//
//   node tools/status.mjs                       what's next up
//   node tools/status.mjs --section 5           what's queued in one section
//   node tools/status.mjs T021 researching
//   node tools/status.mjs T021 researched
//   node tools/status.mjs T021 drafted 001-idempotency
//   node tools/status.mjs T021 posted
//
// Nothing gets designed before its brief exists — see content/research/README.md.
//   node tools/status.mjs --stats               progress across all 18 sections
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const path = join(root, "content/topics.json");
const db = JSON.parse(readFileSync(path, "utf8"));
const STATUSES = ["queued", "researching", "researched", "drafted", "posted", "skipped"];
const args = process.argv.slice(2);

const save = () => writeFileSync(path, JSON.stringify(db, null, 2) + "\n");
const pad = (s, n) => String(s).padEnd(n);

if (args[0] === "--stats") {
  const by = (st) => db.topics.filter((t) => t.status === st).length;
  console.log(`${db.totalTopics} topics — ` +
    STATUSES.map((s) => `${by(s)} ${s}`).join(", "));
  for (const sec of db.sections) {
    const inSec = db.topics.filter((t) => t.section === sec.n);
    const done = inSec.filter((t) => t.status === "posted").length;
    const bar = "█".repeat(Math.round((done / inSec.length) * 18)).padEnd(18, "·");
    console.log(`  ${pad(sec.n, 3)} ${bar} ${pad(`${done}/${inSec.length}`, 8)} ${sec.title}`);
  }
} else if (args[0] === "--section") {
  const n = Number(args[1]);
  for (const t of db.topics.filter((x) => x.section === n)) {
    console.log(`  ${t.id}  ${pad(t.status, 8)} ${t.title}`);
  }
} else if (!args.length) {
  const next = db.topics.filter((t) => t.status === "queued").slice(0, 10);
  console.log(`next up (${db.topics.filter((t) => t.status === "queued").length} queued):`);
  for (const t of next) console.log(`  ${t.id}  [${t.sectionTitle}]  ${t.title}`);
} else {
  const [id, status, dir] = args;
  const t = db.topics.find((x) => x.id === id || x.title === id);
  if (!t) { console.error(`no topic matching "${id}"`); process.exit(1); }
  if (!STATUSES.includes(status)) {
    console.error(`status must be one of: ${STATUSES.join(", ")}`); process.exit(1);
  }
  t.status = status;
  if (dir) t.postDir = dir.startsWith("content/") ? dir : `content/posts/${dir}`;
  if (status === "researching" || status === "researched") {
    t.researchDir = t.researchDir || `content/research/${t.id}-<slug>`;
  }
  if (status === "posted") t.postedAt = new Date().toISOString().slice(0, 10);
  save();
  console.log(`${t.id} → ${status}${t.postDir ? `  (${t.postDir})` : ""}\n  ${t.title}`);
}
