// Chat with a running session (mode B): its recent conversation, read from the session's
// transcript by the daemon, plus a reply box when the daemon can type into it (terminal
// sessions driven through herdr). IDE sessions (VS Code…) cannot receive text from
// outside, so there the reply box starts a widget chat from a COPY of the session
// (« Continuer dans le widget »); the widget still answers their approvals and questions.
import { h } from "../dom";
import { historyView, MORE_STEP, INITIAL_EXCHANGES, type Exchange } from "../exchanges";
import type { Transcript } from "../types";
import { bubble, composer } from "./messages";

export interface TranscriptHandlers {
  setDraft(text: string): void;
  send(text: string): void;
  /** Start a widget chat from a copy of this session. */
  fork(text: string): void;
  /** Reveal older exchanges (may fetch more messages from the daemon). */
  more(): void;
}

/** How much of the conversation is revealed, kept by the caller across refreshes. */
export interface HistoryState {
  readonly shown: number;
  readonly fetchedLimit: number;
}

/** The two parts of a session conversation: the reply box goes at the top of the panel,
 * the history (newest exchange first) lower down. */
export interface Conversation {
  readonly box: readonly HTMLElement[];
  readonly log: HTMLElement;
}

function replyBox(sessionId: string, t: Transcript, draft: string, on: TranscriptHandlers): HTMLElement[] {
  if (t.can_prompt) {
    return [composer({
      key: `session-${sessionId}`,
      placeholder: "Écrire à cette session…",
      label: "Message à la session",
      draft,
      busy: false,
      onDraft: on.setDraft,
      onSend: on.send,
    })];
  }
  return [
    h(
      "p",
      {
        class: "notice",
        title: "La session d'origine n'est pas modifiée. Ses autorisations et questions arrivent ici.",
      },
      "Session dans un IDE ou un terminal : continuez-la ici, dans une copie (l'originale n'est pas modifiée).",
    ),
    composer({
      key: `fork-${sessionId}`,
      placeholder: "Continuer cette conversation dans le widget…",
      label: "Continuer dans le widget",
      draft,
      busy: false,
      onDraft: on.setDraft,
      onSend: on.fork,
    }),
  ];
}

function exchangeItem(exchange: Exchange): HTMLElement {
  return h("li", { class: "exchange" }, h("ol", { class: "exchange__msgs", "aria-label": "Échange" }, ...exchange.map((m) => bubble(m, "Claude"))));
}

function moreLabel(older: number): string {
  const count = Math.min(MORE_STEP, older);
  if (older === 0) return "Afficher des échanges plus anciens";
  return `Afficher ${count} échange${count > 1 ? "s" : ""} plus ancien${count > 1 ? "s" : ""} (${older} restant${older > 1 ? "s" : ""})`;
}

function historyLog(t: Transcript, history: HistoryState, on: TranscriptHandlers): HTMLElement[] {
  const view = historyView(t.messages, history.shown, history.fetchedLimit);
  if (view.exchanges.length === 0) return [h("p", { class: "empty chat__empty" }, "Aucun message pour l'instant.")];
  const parts: HTMLElement[] = [
    h("ol", { class: "session__log", "aria-label": "Messages, du plus récent au plus ancien" }, ...view.exchanges.map(exchangeItem)),
  ];
  if (view.older > 0 || view.maybeMore) {
    parts.push(h("button", { class: "btn btn--ghost history__more", type: "button", onclick: on.more }, moreLabel(view.older)));
  } else if (history.shown > INITIAL_EXCHANGES) {
    parts.push(h("p", { class: "setting__hint" }, "Début de la conversation : rien de plus ancien."));
  }
  return parts;
}

export function transcriptSection(
  sessionId: string,
  t: Transcript | null,
  draft: string,
  history: HistoryState,
  on: TranscriptHandlers,
): Conversation {
  const title = h("h2", { class: "section-title" }, "Conversation");
  const content =
    t === null
      ? [h("p", { class: "setting__hint" }, "Conversation indisponible pour cette session.")]
      : historyLog(t, history, on);
  return {
    box: t === null ? [] : replyBox(sessionId, t, draft, on),
    log: h("section", { class: "transcript", "aria-label": "Conversation de la session" }, title, ...content),
  };
}
