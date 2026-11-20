// Run with: node --test src/react/about-model.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { aboutRows } from "./about-model.ts";

test("shows the widget version and the engine link as labelled rows", () => {
  const rows = aboutRows("0.2.3", { state: "connected", message: "Connecté" });
  assert.deepEqual(rows, [
    { label: "Version du widget", value: "0.2.3" },
    { label: "Moteur local", value: "Connecté" },
  ]);
});

test("falls back to a readable text when the version is unknown", () => {
  const rows = aboutRows("", { state: "connecting", message: "Connexion au démon…" });
  assert.equal(rows[0]?.value, "inconnue");
});

test("an empty link message still says something", () => {
  const rows = aboutRows("0.2.3", { state: "offline", message: "" });
  assert.equal(rows[1]?.value, "Hors ligne");
});
