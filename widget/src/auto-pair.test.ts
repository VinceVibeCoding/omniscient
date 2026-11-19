// Run with: node --test src/auto-pair.test.ts  (Node 22.6+ strips the types; no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import { needsPairingCode } from "./auto-pair.ts";

const link = (state: string, message = "") => ({ state, message }) as never;

test("an unpaired widget asks for a code, once", () => {
  assert.equal(needsPairingCode(link("unpaired", "Aucun couplage"), false), true);
  assert.equal(needsPairingCode(link("unpaired"), true), false);
});

test("a daemon that does not recognize the widget asks for a code", () => {
  const msg = "Ce démon ne reconnaît pas le widget (couplage révoqué ou autre programme) : recouplez-le.";
  assert.equal(needsPairingCode(link("unauthorized", msg), false), true);
});

test("other states and errors never ask", () => {
  assert.equal(needsPairingCode(link("connected"), false), false);
  assert.equal(needsPairingCode(link("offline", "ne reconnaît pas le widget"), false), false);
  assert.equal(needsPairingCode(link("unauthorized", "jeton expiré"), false), false);
});
