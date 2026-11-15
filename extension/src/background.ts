// Service worker: opens the side panel from the toolbar icon, keeps the last failed
// requests of each tab (in memory for the session, reset on every new page), and shows
// « ON » on tabs whose page will be attached (any web page, unless the person unticked it).
// The console-error collector is a static content script (manifest.json).
import { DAEMON_DEFAULT, originOf, pageKey, pushCapped, shareableOrigin, stripQuery } from "./lib/util.js";

const LIST_MAX = 30;
// The string values Chrome expects (the typings model them as an enum).
const TYPES = ["main_frame", "sub_frame", "xmlhttprequest", "script", "stylesheet"] as unknown as chrome.webRequest.ResourceType[];
const MAIN_FRAME = ["main_frame"] as unknown as chrome.webRequest.ResourceType[];
const FILTER: chrome.webRequest.RequestFilter = { urls: ["http://*/*", "https://*/*"], types: TYPES };

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((err: unknown) => console.warn("omnigroup: side panel", err));

async function daemonBase(): Promise<string> {
  const { base } = await chrome.storage.local.get("base");
  return typeof base === "string" ? base : DAEMON_DEFAULT;
}

async function record(tabId: number, item: { method: string; url: string; status: number }): Promise<void> {
  if (tabId < 0 || originOf(item.url) === originOf(await daemonBase())) return; // not the daemon's own traffic
  const key = `net:${tabId}`;
  const current = (await chrome.storage.session.get(key))[key];
  const list = Array.isArray(current) ? current : [];
  await chrome.storage.session.set({ [key]: pushCapped(list, { ...item, url: stripQuery(item.url) }, LIST_MAX) });
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

async function badge(tabId: number, url: string | undefined): Promise<void> {
  const key = `skip:${tabId}`;
  const skipped = (await chrome.storage.session.get(key))[key] === pageKey(url);
  const on = shareableOrigin(url, await daemonBase()) !== null && !skipped;
  await chrome.action.setBadgeText({ tabId, text: on ? "ON" : "" });
  if (on) await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1f9d6b" });
}

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId).then((tab) => badge(tabId, tab.url)).catch(() => undefined);
});
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" || info.url) void badge(tabId, tab.url);
});
chrome.storage.session.onChanged.addListener((changes) => {
  for (const key of Object.keys(changes)) {
    if (!key.startsWith("skip:")) continue;
    const tabId = Number(key.slice(5));
    chrome.tabs.get(tabId).then((tab) => badge(tabId, tab.url)).catch(() => undefined);
  }
});
