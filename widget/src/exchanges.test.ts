// Run with: node --test src/exchanges.test.ts  (Node 22.6+ strips the types; no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import { chronological, groupExchanges, historyView, nextLimit, refetchLimit } from "./exchanges.ts";

const msg = (role: "user" | "assistant" | "tool", text: string, minute: number) => ({
  role, text, at: new Date(Date.UTC(2026, 0, 1, 0, minute)).toISOString(),
});
const talk = (n: number) => Array.from({ length: n }, (_, i) => [msg("user", `q${i}`, i * 2), msg("assistant", `a${i}`, i * 2 + 1)]).flat();

test("groups a user message with the replies that follow", () => {
  const groups = groupExchanges([msg("user", "q", 0), msg("assistant", "a", 1), msg("tool", "t", 2), msg("user", "q2", 3)]);
  assert.deepEqual(groups.map((g) => g.map((m) => m.text)), [["q", "a", "t"], ["q2"]]);
});

test("a leading assistant-only group is one exchange", () => {
  const groups = groupExchanges([msg("assistant", "a0", 0), msg("assistant", "a1", 1), msg("user", "q", 2)]);
  assert.deepEqual(groups.map((g) => g.length), [2, 1]);
});

test("shows the newest exchange first, reading order inside", () => {
  const view = historyView(talk(3), 4, 50);
  assert.deepEqual(view.exchanges.map((e) => e.map((m) => m.text)), [["q2", "a2"], ["q1", "a1"], ["q0", "a0"]]);
  assert.equal(view.older, 0);
});

test("only the last shown exchanges are kept, the rest is counted", () => {
  const view = historyView(talk(10), 4, 50);
  assert.equal(view.exchanges.length, 4);
  assert.equal(view.exchanges[0][0].text, "q9");
  assert.equal(view.older, 6);
  assert.equal(historyView(talk(10), 9, 50).older, 1);
});

test("reorders by time when every message has a valid time", () => {
  const shuffled = [msg("assistant", "a", 1), msg("user", "q", 0)];
  assert.deepEqual(chronological(shuffled).map((m) => m.text), ["q", "a"]);
  const noTime = [{ ...msg("assistant", "a", 1), at: "" }, msg("user", "q", 0)];
  assert.deepEqual(chronological(noTime).map((m) => m.text), ["a", "q"]);
});

test("empty history yields nothing", () => {
  const view = historyView([], 4, 50);
  assert.equal(view.exchanges.length, 0);
  assert.equal(view.older, 0);
  assert.equal(view.maybeMore, false);
});

test("refetches with a larger limit only when the fetch was full and not enough is shown", () => {
  const full = talk(25); // 50 messages = a full fetch
  assert.equal(refetchLimit(full, 9, 50), null); // enough exchanges already
  assert.equal(refetchLimit(full, 30, 50), 100);
  assert.equal(refetchLimit(talk(5), 9, 50), null); // daemon returned less than asked: nothing older
  assert.equal(refetchLimit(talk(100), 90, 200), null); // at the cap
});

test("limit doubles up to the daemon maximum", () => {
  assert.equal(nextLimit(50), 100);
  assert.equal(nextLimit(100), 200);
  assert.equal(nextLimit(200), 200);
});
