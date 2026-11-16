// Pure helpers for a session's conversation: group messages into exchanges (one user
// message plus what follows it), show the newest exchange first, reveal older ones on demand.
import type { ChatMessage } from "./types";

export const INITIAL_EXCHANGES = 4;
export const MORE_STEP = 5;
export const FIRST_LIMIT = 50;
export const MAX_LIMIT = 200;

export type Exchange = readonly ChatMessage[];

export interface HistoryView {
  /** Newest exchange first; messages inside one exchange keep their reading order. */
  readonly exchanges: readonly Exchange[];
  /** Exchanges already fetched but not shown. */
  readonly older: number;
  /** The daemon may hold messages older than what was fetched. */
  readonly maybeMore: boolean;
}

/** Oldest-first order by time when every message has a valid time (stable on ties);
 * otherwise the order received is kept. */
export function chronological(messages: readonly ChatMessage[]): readonly ChatMessage[] {
  const stamped = messages.map((message, index) => ({ message, index, time: Date.parse(message.at) }));
  if (stamped.some((entry) => Number.isNaN(entry.time))) return messages;
  return stamped
    .sort((a, b) => a.time - b.time || a.index - b.index)
    .map((entry) => entry.message);
}

/** A user message opens an exchange; every other message joins the open one. A leading
 * group without a user message counts as one exchange. Result: oldest exchange first. */
export function groupExchanges(messages: readonly ChatMessage[]): readonly Exchange[] {
  const groups: ChatMessage[][] = [];
  for (const message of chronological(messages)) {
    const last = groups[groups.length - 1];
    if (message.role === "user" || last === undefined) groups.push([message]);
    else last.push(message);
  }
  return groups;
}

export function historyView(messages: readonly ChatMessage[], shown: number, fetchedLimit: number): HistoryView {
  const groups = groupExchanges(messages);
  const count = Math.max(1, shown);
  return {
    exchanges: groups.slice(-count).reverse(),
    older: Math.max(0, groups.length - count),
    maybeMore: messages.length >= fetchedLimit && fetchedLimit < MAX_LIMIT,
  };
}

/** The next transcript size to ask the daemon for (doubles, capped). */
export function nextLimit(fetchedLimit: number): number {
  return Math.min(MAX_LIMIT, Math.max(FIRST_LIMIT, fetchedLimit * 2));
}

/** After revealing more: the larger limit to refetch with, or null when what is already
 * fetched is enough (or the daemon has nothing more to give). */
export function refetchLimit(messages: readonly ChatMessage[], shown: number, fetchedLimit: number): number | null {
  const view = historyView(messages, shown, fetchedLimit);
  if (view.exchanges.length >= shown || !view.maybeMore) return null;
  return nextLimit(fetchedLimit);
}
