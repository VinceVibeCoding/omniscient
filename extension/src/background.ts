// Service worker: reports the page you are on to the local Omnigroup daemon, so the widget
// can attach it to a question. It reports when the tab, the page, the selection or the
// console errors change (debounced), for any web page - or only « unticked » when you
// unticked it for this page. The daemon keeps the latest report in memory only.
// It also keeps the last failed requests of each tab and shows « ON » on attachable tabs.
import { Daemon } from "./lib/daemon.js";
import { capturePage, isExcluded } from "./lib/page.js";
import { DAEMON_DEFAULT, originOf, pageKey, pushCapped, shareableOrigin, stripQuery } from "./lib/util.js";

const LIST_MAX = 30;
const REPORT_DELAY_MS = 800;
// The string values Chrome expects (the typings model them as an enum).
const TYPES = ["main_frame", "sub_frame", "xmlhttprequest", "script", "stylesheet"] as unknown as chrome.webRequest.ResourceType[];
const MAIN_FRAME = ["main_frame"] as unknown as chrome.webRequest.ResourceType[];
const FILTER: chrome.webRequest.RequestFilter = { urls: ["http://*/*", "https://*/*"], types: TYPES };

let reportTimer: ReturnType<typeof setTimeout> | undefined;
let lastSent = "";

async function settings(): Promise<{ base: string; token: string | null }> {
  const { base, token } = await chrome.storage.local.get(["base", "token"]);
  return { base: typeof base === "string" ? base : DAEMON_DEFAULT, token: typeof token === "string" ? token : null };
}

/** The daemon, once it proved it knows our token (checked once per browser session). */
async function daemon(): Promise<Daemon | null> {
  const { base, token } = await settings();
  if (!token) return null;
  const candidate = new Daemon(base, token);
  const { verifiedBase } = await chrome.storage.session.get("verifiedBase");
  if (verifiedBase === base) return candidate;
  if (!(await candidate.verify())) return null;
  await chrome.storage.session.set({ verifiedBase: base });
  return candidate;
}

async function activeTab(): Promise<chrome.tabs.Tab | null> {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab ?? null;
}

async function report(): Promise<void> {
  const client = await daemon();
  const tab = await activeTab();
  if (!client || !tab?.url || !shareableOrigin(tab.url, client.base)) return; // browser pages: nothing to say
  const body = (await isExcluded(tab))
    ? { excluded: true as const, url: stripQuery(tab.url), title: tab.title ?? "" }
    : { page: await capturePage(tab, client.base) };
  const fingerprint = JSON.stringify(body);
  if (fingerprint === lastSent) return;
  await client.reportPage(body);
  lastSent = fingerprint;
}

function scheduleReport(): void {
  clearTimeout(reportTimer);
  reportTimer = setTimeout(() => {
    report().catch((err: unknown) => console.warn("omnigroup: page not reported", err));
  }, REPORT_DELAY_MS);
}

async function record(tabId: number, item: { method: string; url: string; status: number }): Promise<void> {
  if (tabId < 0 || originOf(item.url) === originOf((await settings()).base)) return; // not the daemon's own traffic
  const key = `net:${tabId}`;
  const current = (await chrome.storage.session.get(key))[key];
  const list = Array.isArray(current) ? current : [];
  await chrome.storage.session.set({ [key]: pushCapped(list, { ...item, url: stripQuery(item.url) }, LIST_MAX) });
  if (tabId === (await activeTab())?.id) scheduleReport();
}

async function badge(tabId: number, url: string | undefined): Promise<void> {
  const key = `skip:${tabId}`;
  const skipped = (await chrome.storage.session.get(key))[key] === pageKey(url);
  const on = shareableOrigin(url, (await settings()).base) !== null && !skipped;
  await chrome.action.setBadgeText({ tabId, text: on ? "ON" : "" });
  if (on) await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1f9d6b" });
}

chrome.webRequest.onBeforeRequest.addListener(
  (d) => {
    if ((d.type as string) === "main_frame" && d.tabId >= 0) void chrome.storage.session.remove(`net:${d.tabId}`); // a new page
    return undefined;
  },
  { urls: ["http://*/*", "https://*/*"], types: MAIN_FRAME },
);
chrome.webRequest.onCompleted.addListener((d) => {
  if (d.statusCode >= 400) void record(d.tabId, { method: d.method, url: d.url, status: d.statusCode });
}, FILTER);
chrome.webRequest.onErrorOccurred.addListener((d) => {
  if (d.error !== "net::ERR_ABORTED") void record(d.tabId, { method: d.method, url: d.url, status: 0 });
}, FILTER);

chrome.tabs.onRemoved.addListener((tabId) => void chrome.storage.session.remove([`net:${tabId}`, `skip:${tabId}`]));
chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId).then((tab) => badge(tabId, tab.url)).catch(() => undefined);
  scheduleReport();
});
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" || info.url) void badge(tabId, tab.url);
  if (info.status === "complete" && tab.active) scheduleReport();
});
chrome.windows.onFocusChanged.addListener(() => scheduleReport());
chrome.runtime.onMessage.addListener((message: unknown, sender) => {
  if ((message as { type?: unknown } | null)?.type === "page-changed" && sender.tab?.active) scheduleReport();
  return undefined;
});
chrome.storage.session.onChanged.addListener((changes) => {
  for (const key of Object.keys(changes)) {
    if (!key.startsWith("skip:")) continue;
    const tabId = Number(key.slice(5));
    chrome.tabs.get(tabId).then((tab) => badge(tabId, tab.url)).catch(() => undefined);
    scheduleReport();
  }
});
chrome.storage.local.onChanged.addListener((changes) => {
  if ("token" in changes || "base" in changes) {
    void chrome.storage.session.remove("verifiedBase");
    lastSent = "";
    scheduleReport();
  }
});
