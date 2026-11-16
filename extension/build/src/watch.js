"use strict";
// Content script (isolated world) on web pages: tells the extension when the page it may
// report has changed - new console errors, a new selection, the tab shown again - so the
// widget always has the page as it is now. It sends no page data itself: the background
// worker reads the page, and only for a page the person did not untick.
(() => {
    const DELAY_MS = 700;
    let timer;
    const nudge = () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
            chrome.runtime.sendMessage({ type: "page-changed" }).catch(() => undefined); // the worker may be asleep
        }, DELAY_MS);
    };
    window.addEventListener("message", (e) => {
        if (e.source === window && e.data?.__omnigroup === "changed")
            nudge();
    });
    document.addEventListener("selectionchange", nudge);
    document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && nudge());
})();
