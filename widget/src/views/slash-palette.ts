// The suggestion list above the chat box while it holds « /nom ». Updated in place (the
// composer is not rebuilt while typing). Up/Down move, Tab or a click completes, Enter
// completes too unless the name is already complete (then it sends), Escape closes.
import { h } from "../dom";
import { completion, filterEntries, slashQuery, type SlashEntry } from "../ext-logic";

export interface SlashPalette {
  element: HTMLElement;
  /** True when the key was used by the list (the box must not handle it). */
  onKey(event: KeyboardEvent): boolean;
}

const KIND_LABEL = { builtin: "intégrée", command: "commande", workflow: "workflow" } as const;

export function slashPalette(area: HTMLTextAreaElement, entries: readonly SlashEntry[], onDraft: (text: string) => void): SlashPalette {
  const list = h("ul", { class: "slash", role: "listbox", "aria-label": "Commandes", hidden: true });
  let shown: SlashEntry[] = [];
  let selected = 0;
  let dismissed = false;

  const pick = (entry: SlashEntry): void => {
    area.value = completion(entry);
    area.setSelectionRange(area.value.length, area.value.length);
    onDraft(area.value);
    refresh(true);
    area.focus();
  };

  const paint = (): void => {
    list.replaceChildren(
      ...shown.map((entry, i) => {
        const item = h(
          "li",
          { class: `slash__item${i === selected ? " slash__item--on" : ""}`, role: "option", "aria-selected": String(i === selected) },
          h("span", { class: "slash__name" }, `/${entry.name}`),
          h("span", { class: "slash__title" }, entry.title),
          h("span", { class: "slash__kind" }, KIND_LABEL[entry.kind]),
        );
        item.addEventListener("mousedown", (event) => {
          event.preventDefault(); // keeps the focus (and the caret) in the box
          pick(entry);
        });
        return item;
      }),
    );
    list.hidden = shown.length === 0;
    area.setAttribute("aria-expanded", String(!list.hidden));
  };

  function refresh(reset: boolean): void {
    const query = dismissed ? null : slashQuery(area.value);
    shown = query === null ? [] : filterEntries(entries, query);
    if (reset || selected >= shown.length) selected = 0;
    paint();
  }

  area.setAttribute("aria-haspopup", "listbox");
  area.addEventListener("input", () => {
    dismissed = false;
    refresh(true);
  });
  area.addEventListener("focus", () => refresh(false));
  area.addEventListener("blur", () => {
    shown = [];
    paint();
  });

  const onKey = (event: KeyboardEvent): boolean => {
    if (list.hidden || event.isComposing) return false;
    const current = shown[selected];
    const move = (step: number): void => {
      selected = (selected + step + shown.length) % shown.length;
      paint();
    };
    switch (event.key) {
      case "ArrowDown":
        move(1);
        break;
      case "ArrowUp":
        move(-1);
        break;
      case "Tab":
        if (current) pick(current);
        break;
      case "Enter":
        // A complete name is sent as it is; a partial one is completed first.
        if (!current || event.shiftKey || area.value.trim() === `/${current.name}`) return false;
        pick(current);
        break;
      case "Escape":
        dismissed = true;
        event.stopPropagation(); // the panel's own Escape must not close the view
        refresh(true);
        break;
      default:
        return false;
    }
    event.preventDefault();
    return true;
  };

  return { element: list, onKey };
}
