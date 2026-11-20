// Size budget for the built widget: the start-up files must stay small, and the React chunk
// (loaded only when a React screen opens) has its own ceiling. Run after `vite build`:
//   node scripts/size-budget.mjs
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/** Limits set when React was added (ticket 10); each is the measured size plus a small margin. */
export const RULES = [
  { name: "start-up script (main)", pattern: /^main-.*\.js$/, maxBytes: 90_000 },
  { name: "start-up styles (main)", pattern: /^main-.*\.css$/, maxBytes: 26_000 },
  { name: "React screens script (lazy)", pattern: /^mount-.*\.js$/, maxBytes: 540_000 },
  { name: "React screens styles (lazy)", pattern: /^mount-.*\.css$/, maxBytes: 340_000 },
];

/** Returns every rule that a file breaks, or that matches no file at all. */
export function overBudget(files, rules) {
  const out = [];
  for (const rule of rules) {
    const matched = files.filter((f) => rule.pattern.test(f.file));
    if (matched.length === 0) out.push({ rule: rule.name, file: null, bytes: 0, maxBytes: rule.maxBytes });
    for (const f of matched) {
      if (f.bytes > rule.maxBytes) out.push({ rule: rule.name, file: f.file, bytes: f.bytes, maxBytes: rule.maxBytes });
    }
  }
  return out;
}

function builtFiles(dir) {
  return readdirSync(dir).map((file) => ({ file, bytes: statSync(join(dir, file)).size }));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const problems = overBudget(builtFiles("dist/assets"), RULES);
  for (const p of problems) {
    console.error(`${p.rule}: ${p.file ?? "no matching file"} is ${p.bytes} bytes (limit ${p.maxBytes})`);
  }
  if (problems.length > 0) process.exit(1);
  console.log("Size budget respected.");
}
