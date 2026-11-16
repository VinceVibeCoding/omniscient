// Reading the page the person is on, only for a site they allowed. Functions passed to
// chrome.scripting.executeScript run inside the page, so they must be self-contained.
import { pageKey, shareableOrigin, stripQuery } from "./util.js";
const TEXT_MAX = 20_000;
const SELECTION_MAX = 4_000;
const LIST_MAX = 30;
const OUTLINE_MAX = 80;
/** Runs in the page (isolated world): visible text, selection, title. Field values (and so
 * passwords) are not part of innerText. */
function readVisible() {
    const text = (document.body?.innerText ?? "").replace(/\n{3,}/g, "\n\n");
    return { url: location.href, title: document.title, text: text.slice(0, 20_000), selection: String(window.getSelection() ?? "").slice(0, 4_000) };
}
/** Runs in the page (isolated world): the headings, landmarks and controls with where each one
 * is on the screen, as short text (« visible, en haut à droite »). Never reads field values
 * (passwords), nor link addresses (they often carry tokens). Self-contained: it is serialised. */
function readOutline() {
    const vw = window.innerWidth || 1;
    const vh = window.innerHeight || 1;
    const place = (r) => {
        if (r.bottom <= 0)
            return "plus haut dans la page (hors de l'écran)";
        if (r.top >= vh)
            return `plus bas dans la page (à environ ${Math.max(1, Math.round((r.top - vh) / vh + 0.5))} écran(s) sous l'écran visible)`;
        const cx = (r.left + r.right) / 2 / vw;
        const cy = (r.top + r.bottom) / 2 / vh;
        const row = cy < 0.33 ? "en haut" : cy > 0.66 ? "en bas" : "au milieu";
        const col = cx < 0.33 ? "à gauche" : cx > 0.66 ? "à droite" : "au centre";
        return `visible, ${row} ${col}`;
    };
    const roleOf = (el) => {
        const tag = el.tagName.toLowerCase();
        if (/^h[1-3]$/.test(tag))
            return "heading";
        if (tag === "a")
            return "link";
        if (tag === "input" || tag === "select" || tag === "textarea")
            return "field";
        if (tag === "button" || el.getAttribute("role") === "button")
            return "button";
        return tag; // nav, main, header, footer, aside
    };
    const labelOf = (el) => {
        const aria = el.getAttribute("aria-label");
        const own = el.innerText ?? "";
        const field = el;
        const named = aria || (field.labels?.[0]?.innerText ?? "") || field.placeholder || field.name || "";
        const text = roleOf(el) === "field" ? named : own || named;
        return text.replace(/\s+/g, " ").trim().slice(0, 100);
    };
    const seen = new Set();
    const collect = (selector, cap) => {
        const out = [];
        for (const el of document.querySelectorAll(selector)) {
            if (out.length >= cap)
                break;
            const rect = el.getBoundingClientRect();
            if (rect.width < 2 || rect.height < 2 || (el.checkVisibility && !el.checkVisibility()))
                continue;
            if (el instanceof HTMLInputElement && ["hidden", "password"].includes(el.type))
                continue;
            const role = roleOf(el);
            const text = labelOf(el);
            const key = `${role}|${text}|${Math.round(rect.top / 40)}`;
            if (!text && !["nav", "main", "header", "footer", "aside"].includes(role))
                continue;
            if (seen.has(key))
                continue;
            seen.add(key);
            out.push({ role, text: text || role, where: place(rect) });
        }
        return out;
    };
    return [
        ...collect("h1, h2, h3, nav, main, header, footer, aside", 30),
        ...collect("button, [role=button], a[href], input, select, textarea", 50),
    ];
}
/** Runs in the page (main world): the console errors capture-main.js collected. */
function readErrors() {
    const list = window.__omnigroupErrors;
    return Array.isArray(list) ? list.filter((e) => typeof e === "string").slice(-30) : [];
}
/** True when the person unticked « Joindre cette page » for the page this tab is on. */
export async function isExcluded(tab) {
    if (tab?.id === undefined)
        return false;
    const key = `skip:${tab.id}`;
    return (await chrome.storage.session.get(key))[key] === pageKey(tab.url);
}
/** Untick / tick for this page only: a new page in the tab starts ticked again. */
export async function setExcluded(tab, excluded) {
    if (tab.id === undefined)
        return;
    const key = `skip:${tab.id}`;
    if (excluded)
        await chrome.storage.session.set({ [key]: pageKey(tab.url) });
    else
        await chrome.storage.session.remove(key);
}
/** Everything about the tab (only called when the person sends with the box ticked). */
export async function capturePage(tab, daemonBase) {
    if (tab.id === undefined || !shareableOrigin(tab.url, daemonBase))
        throw new Error("Cette page ne peut pas être jointe.");
    const target = { tabId: tab.id };
    const [visible] = await chrome.scripting.executeScript({ target, func: readVisible });
    const [outline] = await chrome.scripting.executeScript({ target, func: readOutline }).catch(() => [{ result: [] }]);
    const [errors] = await chrome.scripting.executeScript({ target, func: readErrors, world: "MAIN" }).catch(() => [{ result: [] }]);
    const key = `net:${tab.id}`;
    const stored = (await chrome.storage.session.get(key))[key];
    const page = visible?.result;
    if (!page)
        throw new Error("Impossible de lire cette page.");
    return {
        url: stripQuery(page.url),
        title: page.title.slice(0, 300),
        text: page.text.slice(0, TEXT_MAX),
        selection: page.selection.slice(0, SELECTION_MAX),
        errors: (errors?.result ?? []).slice(-LIST_MAX),
        network: Array.isArray(stored) ? stored.slice(-LIST_MAX) : [],
        outline: Array.isArray(outline?.result) ? outline.result.slice(0, OUTLINE_MAX) : [],
    };
}
