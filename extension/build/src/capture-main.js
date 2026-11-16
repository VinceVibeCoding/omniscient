"use strict";
// Content script injected at document_start in the page's own world, only on sites the
// person allowed: it keeps the last console errors so the side panel can attach them.
// Nothing is sent anywhere from here: it only nudges watch.js that the page changed, and
// the extension reads the list when it reports the page to the local daemon.
(() => {
    const MAX = 30;
    const ITEM_MAX = 300;
    const w = window;
    if (w.__omnigroupErrors)
        return;
    const errors = [];
    Object.defineProperty(window, "__omnigroupErrors", { value: errors, enumerable: false });
    const push = (text) => {
        errors.push(text.slice(0, ITEM_MAX));
        if (errors.length > MAX)
            errors.splice(0, errors.length - MAX);
        window.postMessage({ __omnigroup: "changed" }, location.origin); // just a nudge, no data
    };
    const show = (value) => {
        if (value instanceof Error)
            return `${value.name}: ${value.message}`;
        try {
            return typeof value === "string" ? value : JSON.stringify(value);
        }
        catch {
            return String(value);
        }
    };
    window.addEventListener("error", (e) => push(`${e.message} (${e.filename?.split("?")[0] ?? ""}:${e.lineno ?? 0})`));
    window.addEventListener("unhandledrejection", (e) => push(`Unhandled rejection: ${show(e.reason)}`));
    const original = console.error.bind(console);
    console.error = (...args) => {
        push(args.map(show).join(" "));
        original(...args);
    };
})();
