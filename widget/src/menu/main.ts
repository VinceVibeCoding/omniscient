// The OSD's right-click menu (window "menu", menu.html). Rust shows it at the cursor
// with a fresh snapshot (`menu://open`); a pick goes back through `menu_pick`, and
// Escape / a click outside close it. Arrow keys move between items.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { replace } from "../dom";
import { applySkin, applyTheme } from "../theme";
import { DEFAULT_SNAPSHOT, type MenuSnapshot, toSnapshot } from "./model";
import { menuView } from "./view";

const root = document.getElementById("menu") as HTMLElement;
let paletteLoaded = false;

function items(): HTMLButtonElement[] {
  return [...root.querySelectorAll<HTMLButtonElement>("button[data-id]:not([disabled])")];
}

function render(snap: MenuSnapshot): void {
  applySkin(snap.theme);
  replace(root, menuView(snap));
  fit();
}

/** Tells Rust the menu's size so the window hugs it (next opening). */
function fit(): void {
  const box = root.getBoundingClientRect();
  void invoke("menu_fit", { width: Math.ceil(box.width), height: Math.ceil(box.height) }).catch((err) =>
    console.warn("omniscient menu: size not sent", err),
  );
}

async function loadPalette(): Promise<void> {
  if (paletteLoaded) return;
  try {
    applyTheme(await invoke<unknown>("get_theme"));
    paletteLoaded = true;
  } catch (err) {
    console.warn("omniscient menu: home palette unavailable, default kept", err); // retried next opening
  }
}

function close(): void {
  void invoke("menu_close").catch((err) => console.warn("omniscient menu: not closed", err));
}

function pick(id: string): void {
  void invoke("menu_pick", { id }).catch((err) => console.warn("omniscient menu: pick refused", err));
}

function move(step: number): void {
  const list = items();
  if (list.length === 0) return;
  const at = list.indexOf(document.activeElement as HTMLButtonElement);
  const next = at < 0 ? (step > 0 ? 0 : list.length - 1) : (at + step + list.length) % list.length;
  list[next]?.focus();
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") close();
  else if (event.key === "ArrowDown") move(1);
  else if (event.key === "ArrowUp") move(-1);
  else return;
  event.preventDefault();
}

function onClick(event: MouseEvent): void {
  const target = event.target as Element | null;
  const button = target?.closest<HTMLButtonElement>("button[data-id]");
  if (button && !button.disabled && button.dataset.id) pick(button.dataset.id);
  else if (!target?.closest(".menu")) close(); // the transparent margin around the menu
}

async function main(): Promise<void> {
  render(DEFAULT_SNAPSHOT);
  document.addEventListener("keydown", onKey);
  document.addEventListener("click", onClick);
  document.addEventListener("contextmenu", (event) => event.preventDefault());
  await listen<unknown>("menu://open", (event) => {
    render(toSnapshot(event.payload));
    void loadPalette();
  });
}

void main();
