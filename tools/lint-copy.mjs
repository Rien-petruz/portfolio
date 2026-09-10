// Checks post copy against content/STYLE.md before it gets rendered.
//
//   node tools/lint-copy.mjs content/posts/001-idempotency
//   node tools/lint-copy.mjs --all
//
// Rule 1 is the one that bites: no dashes anywhere in published copy. Code
// syntax, URLs, the handle and markdown structure are legitimately exempt,
// so those are stripped before the check rather than reported as noise.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, relative } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const argv = process.argv.slice(2);
const postsRoot = join(root, "content/posts");
const dirs = argv.includes("--all")
  ? readdirSync(postsRoot).filter((d) => existsSync(join(postsRoot, d))).sort()
      .map((d) => join(postsRoot, d))
  : argv.filter((x) => !x.startsWith("--")).map((p) => resolve(p));

if (!dirs.length) {
  console.error("usage: node tools/lint-copy.mjs <postDir> [...] | --all");
  process.exit(1);
}

const DASH = /[—–]|\w-\w/;

/** Remove the things a dash is legitimately part of. */
function scrub(text) {
  return text
    .replace(/```[\s\S]*?```/g, "")        // fenced code
    .replace(/`[^`\n]*`/g, "")             // inline code
    .replace(/https?:\/\/\S+/g, "")        // URLs
    .replace(/\]\([^)]*\)/g, "")           // link targets
    .replace(/@peter-kekpe/g, "")          // the handle
    .replace(/[\w.@-]+\/[\w./@-]+/g, "")  // file and folder paths
    .replace(/^\s*-{3,}\s*$/gm, "")        // front matter / horizontal rules
    .replace(/^\s*\|[\s|:-]+\|\s*$/gm, "") // table separator rows
    .replace(/^\s*-\s/gm, " ");            // list bullets
}

let problems = 0;

for (const dir of dirs) {
  const name = relative(root, dir);
  const found = [];

  // slides.json — walk every string, skipping code payloads
  const slidesPath = join(dir, "slides.json");
  if (existsSync(slidesPath)) {
    const walk = (node, path) => {
      if (node && typeof node === "object") {
        for (const [k, v] of Object.entries(node)) {
          if (k === "code") continue;      // real syntax, leave it correct
          walk(v, Array.isArray(node) ? `${path}[${k}]` : `${path}.${k}`);
        }
      } else if (typeof node === "string") {
        for (const line of scrub(node).split("\n")) {
          if (DASH.test(line)) found.push([`slides.json ${path}`, line.trim()]);
        }
      }
    };
    walk(JSON.parse(readFileSync(slidesPath, "utf8")).slides, "slides");
  }

  // prose files
  for (const file of ["post.md", "captions.md"]) {
    const p = join(dir, file);
    if (!existsSync(p)) continue;
    scrub(readFileSync(p, "utf8")).split("\n").forEach((line, i) => {
      if (DASH.test(line)) found.push([`${file}:${i + 1}`, line.trim()]);
    });
  }

  if (found.length) {
    problems += found.length;
    console.log(`\n${name}  ${found.length} dash issue(s)`);
    for (const [where, line] of found) console.log(`  ${where}\n    ${line.slice(0, 96)}`);
  } else {
    console.log(`${name}  clean`);
  }
}

if (problems) {
  console.log(`\n${problems} issue(s). See content/STYLE.md rule 1.`);
  process.exit(1);
}
