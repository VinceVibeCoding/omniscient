// Conversation log + composer shared by the widget chat (mode A) and a running session's
// transcript (mode B). The composer is not a <form>: main.ts keeps rendering while it has
// focus and restores its text and caret through `data-keep`, so streamed replies show up
// while the owner types. Enter sends, Shift+Enter adds a line.
import { h } from "../dom";
import { age, clip } from "../format";
import type { SlashEntry } from "../ext-logic";
import type { ChatMessage } from "../types";
import { slashPalette } from "./slash-palette";

const MAX_TEXT = 20_000;
const SHOWN_CHARS = 8000;

const ROLE_LABEL: Record<ChatMessage["role"], string> = {
  user: "Vous",
  assistant: "Claude",
  tool: "Outil",
  error: "Erreur",
  note: "Omniscient",
};

const ELEMENT_REF = /\[#(\d{1,3})\]/g;

/** The text with each « [#12] » Claude wrote turned into a « Montrer » button (that frames
 * element 12 of the page on the screen). Text only: nothing in it can run. */
function withShowButtons(text: string, show: (n: number) => void): (string | HTMLElement)[] {
  const parts: (string | HTMLElement)[] = [];
  let last = 0;
  for (const match of text.matchAll(ELEMENT_REF)) {
    const n = Number(match[1]);
    parts.push(text.slice(last, match.index));
    parts.push(h("button", { class: "msg__show", type: "button", title: `Montrer l'élément n° ${n} sur la page`, onclick: () => show(n) }, `▸ Montrer #${n}`));
    last = match.index + match[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

export function bubble(m: ChatMessage, assistant: string, show?: (n: number) => void): HTMLElement {
  if (m.role === "note") return h("li", { class: "msg msg--note", role: "note" }, h("p", { class: "msg__text" }, clip(m.text, SHOWN_CHARS)));
  const base = m.role === "assistant" ? assistant : ROLE_LABEL[m.role];
  const who = m.role === "tool" && m.tool ? `${ROLE_LABEL.tool} · ${m.tool}` : base;
  return h(
    "li",
    { class: `msg msg--${m.role}` },
    h("div", { class: "msg__head" }, h("span", { class: "msg__who" }, who), m.at ? h("time", { datetime: m.at }, age(m.at)) : null),
    m.text ? h("p", { class: "msg__text" }, ...(show ? withShowButtons(clip(m.text, SHOWN_CHARS), show) : [clip(m.text, SHOWN_CHARS)])) : null,
  );
}

/** `assistant`: who answers (« Claude », or the name of another provider). */
export function messageLog(
  messages: readonly ChatMessage[],
  empty: string,
  key: string,
  assistant = ROLE_LABEL.assistant,
  show?: (n: number) => void,
): HTMLElement {
  if (messages.length === 0) return h("p", { class: "empty chat__empty" }, empty);
  // Only the latest answer can point at elements: the numbers belong to the page last sent.
  const latest = messages.map((m) => m.role).lastIndexOf("assistant");
  return h("ol", { class: "chat__log", "data-scroll": key, "aria-label": "Messages" }, ...messages.map((m, i) => bubble(m, assistant, i === latest ? show : undefined)));
}

export interface ComposerOptions {
  key: string; // data-keep id: text + caret survive re-renders
  placeholder: string;
  label: string;
  draft: string;
  busy: boolean;
  onDraft(text: string): void;
  onSend(text: string): void;
  /** Suggestions shown while the box holds « /nom » (the chat only). */
  slash?: readonly SlashEntry[];
}

export function composer(o: ComposerOptions): HTMLElement {
  const area = h("textarea", {
    class: "composer__input",
    rows: 2,
    maxlength: MAX_TEXT,
    placeholder: o.placeholder,
    "aria-label": o.label,
    "data-keep": o.key,
  });
  area.value = o.draft;
  const palette = o.slash ? slashPalette(area, o.slash, o.onDraft) : null;
  const send = (): void => {
    const text = area.value.trim();
    if (!text || o.busy) return;
    area.value = "";
    o.onDraft("");
    o.onSend(text);
  };
  area.addEventListener("input", () => o.onDraft(area.value));
  area.addEventListener("keydown", (event) => {
    if (palette?.onKey(event)) return;
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });
  return h(
    "div",
    { class: "composer" },
    palette?.element ?? null,
    area,
    h("button", { class: "btn btn--primary", type: "button", disabled: o.busy, onclick: send }, "Envoyer"),
  );
}
