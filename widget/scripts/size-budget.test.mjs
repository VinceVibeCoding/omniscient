// Run with: node --test scripts/size-budget.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { overBudget } from "./size-budget.mjs";

const RULES = [
  { name: "start-up script", pattern: /^main-.*\.js$/, maxBytes: 90_000 },
  { name: "start-up styles", pattern: /^main-.*\.css$/, maxBytes: 26_000 },
];

test("accepts files within their budget", () => {
  const files = [{ file: "main-abc.js", bytes: 83_840 }, { file: "main-abc.css", bytes: 24_150 }];
  assert.deepEqual(overBudget(files, RULES), []);
});

test("names the rule, the file and the excess when a file is too big", () => {
  const files = [{ file: "main-abc.js", bytes: 91_000 }, { file: "main-abc.css", bytes: 1 }];
  assert.deepEqual(overBudget(files, RULES), [
    { rule: "start-up script", file: "main-abc.js", bytes: 91_000, maxBytes: 90_000 },
  ]);
});

test("a file that matches no rule is ignored", () => {
  const files = [{ file: "main-abc.js", bytes: 1 }, { file: "main-abc.css", bytes: 1 }, { file: "menu-x.js", bytes: 10_000_000 }];
  assert.deepEqual(overBudget(files, RULES), []);
});

test("a rule that matches no file is reported, so a renamed chunk cannot hide", () => {
  const out = overBudget([{ file: "main-abc.js", bytes: 1 }], RULES);
  assert.deepEqual(out, [{ rule: "start-up styles", file: null, bytes: 0, maxBytes: 26_000 }]);
});
