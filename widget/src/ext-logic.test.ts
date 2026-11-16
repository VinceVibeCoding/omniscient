// Run with: node --test src/ext-logic.test.ts  (Node 22.6+ strips the types; no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BUILTIN_ENTRIES, buildEntries, filterEntries, isThemeColor, mergeNotes, nextStep, onChatState,
  parseSlash, reloadNote, safeThemeColors, slashQuery, startRun,
} from "./ext-logic.ts";

const view = {
  extensions: [
    { id: "a", name: "A", description: "", version: "1.0.0", author: "", enabled: true, themes: [], presets: [],
      commands: [{ name: "resume", title: "Résumer", args: [], attachPage: true }],
      workflows: [{ name: "review", title: "Relecture", needsProject: true, steps: ["un", "deux"] }] },
    { id: "b", name: "B", description: "", version: "1.0.0", author: "", enabled: false, themes: [], presets: [],
      commands: [{ name: "hidden", title: "Caché", args: [], attachPage: false }], workflows: [] },
  ],
  errors: [{ id: "c", message: "manifeste invalide" }],
};

test("slashQuery only matches a partial name at the start", () => {
  assert.equal(slashQuery("/"), "");
  assert.equal(slashQuery("/res"), "res");
  assert.equal(slashQuery("/resume 7"), null);
  assert.equal(slashQuery("salut /x"), null);
  assert.equal(slashQuery("/Bad"), null);
});

test("entries: built-ins, enabled commands and workflows, filtered", () => {
  const names = buildEntries(view).map((e) => e.name);
  assert.deepEqual(names, ["reload", "extensions", "resume", "review"]);
  assert.deepEqual(filterEntries(buildEntries(view), "re").map((e) => e.name), ["reload", "resume", "review"]);
  assert.deepEqual(filterEntries(BUILTIN_ENTRIES, "zzz"), []);
  assert.equal(filterEntries(buildEntries(view), "", 2).length, 2);
});

test("parseSlash splits the name and the arguments", () => {
  assert.deepEqual(parseSlash("/resume 7 points"), { name: "resume", args: "7 points" });
  assert.deepEqual(parseSlash("  /reload "), { name: "reload", args: "" });
  assert.equal(parseSlash("bonjour"), null);
  assert.equal(parseSlash("/Usr/bin"), null);
  assert.equal(parseSlash("/ x"), null);
});

test("theme colours: hex and rgb only, allowlisted properties only", () => {
  for (const ok of ["#fff", "#aabbcc", "#aabbccdd", "rgb(0, 10, 255)", "rgba(1,2,3,.5)", "rgba(1,2,3,1)"]) assert.ok(isThemeColor(ok), ok);
  for (const bad of ["red", "url(x)", "var(--a)", "#ggg", "rgb(256,0,0)", "#12345", "rgb(1,2,3);x", 5, null]) assert.ok(!isThemeColor(bad), String(bad));
  const safe = safeThemeColors({ "--accent": "#fff", "--evil": "#000", "--border": "url(x)", __proto__: "#fff", "--ring": "rgb(1,2,3)" });
  assert.deepEqual(safe, [["--accent", "#fff"], ["--ring", "rgb(1,2,3)"]]);
});

test("workflow steps go one at a time and stop on error", () => {
  let run = startRun("review", ["un", "deux"]);
  const first = nextStep(run);
  assert.ok(first.kind === "send" && first.prompt === "un" && first.index === 1 && first.total === 2);
  run = first.kind === "send" ? first.run : run;
  assert.equal(onChatState(run, "running").kind, "ignore");
  const turn = onChatState(run, "idle");
  assert.equal(turn.kind, "advance");
  run = turn.kind === "advance" ? turn.run : run;
  assert.equal(onChatState(run, "idle").kind, "ignore"); // nothing awaited: a duplicate idle is ignored
  const second = nextStep(run);
  assert.ok(second.kind === "send" && second.prompt === "deux");
  run = second.kind === "send" ? second.run : run;
  assert.equal(onChatState(run, "error").kind, "stop");
  assert.equal(nextStep({ ...run, next: 2 }).kind, "done");
});

test("notes are slotted by time and the notes text counts the errors", () => {
  const at = (s: string) => `2026-01-01T00:00:0${s}Z`;
  const msgs = [{ role: "user" as const, text: "a", at: at("1") }, { role: "assistant" as const, text: "b", at: at("5") }];
  const note = { role: "note" as const, text: "n", at: at("3") };
  assert.deepEqual(mergeNotes(msgs, [note]).map((m) => m.text), ["a", "n", "b"]);
  assert.equal(mergeNotes(msgs, []), msgs);
  const text = reloadNote(view);
  assert.match(text, /^Extensions rechargées : 2 commandes, 0 thème, 0 préréglage \(1 erreur\)\n• c : manifeste invalide$/);
});
